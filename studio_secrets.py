"""Current-user DPAPI envelopes for explicitly saved studio API keys."""
import base64
import binascii
import ctypes
import sys


_PREFIX = "dpapi-v1:"
_NO_UI = 0x1  # CRYPTPROTECT_UI_FORBIDDEN; protection defaults to the current user.
_BLOB_LIMIT = 16 * 1024


class KeyProtectionError(ValueError):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("data", ctypes.c_void_p)]


def supports_key_protection():
    return sys.platform == "win32"


def _dpapi(data, *, encrypt):
    if not supports_key_protection():
        raise KeyProtectionError("当前系统未提供 Windows 用户密钥保护。")
    try:
        crypt32 = ctypes.WinDLL("crypt32")
        operation = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
        # Both calls accept NULL for description, entropy, reserved and prompt.
        operation.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                              ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_Blob)]
        operation.restype = ctypes.c_int
        local_free = ctypes.WinDLL("kernel32").LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        buffer = ctypes.create_string_buffer(data)
        source = _Blob(len(data), ctypes.addressof(buffer))
        output = _Blob()
        try:
            if not operation(ctypes.byref(source), None, None, None, None, _NO_UI, ctypes.byref(output)):
                raise KeyProtectionError("Windows 无法使用当前用户的密钥保护。")
            return ctypes.string_at(output.data, output.length)
        finally:
            if output.data:
                if not encrypt:
                    ctypes.memset(output.data, 0, output.length)
                local_free(output.data)
            if encrypt:
                ctypes.memset(ctypes.addressof(buffer), 0, len(buffer))
    except (AttributeError, OSError):
        raise KeyProtectionError("Windows 用户密钥保护不可用。") from None


def _valid_key(key):
    return (isinstance(key, str) and 1 <= len(key) <= 512 and key == key.strip()
            and key.isascii() and key.isprintable())


def protect_key(plaintext: str) -> str:
    if not _valid_key(plaintext):
        raise KeyProtectionError("API Key 格式不正确。")
    encrypted = _dpapi(plaintext.encode("ascii"), encrypt=True)
    return _PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect_key(ciphertext: str) -> str:
    if (not isinstance(ciphertext, str) or len(ciphertext) > _BLOB_LIMIT
            or not ciphertext.startswith(_PREFIX) or not ciphertext.isascii()):
        raise KeyProtectionError("已存密钥格式无效。")
    try:
        blob = base64.b64decode(ciphertext[len(_PREFIX):], validate=True)
        if not blob:
            raise KeyProtectionError("已存密钥为空。")
        plaintext = _dpapi(blob, encrypt=False).decode("ascii")
    except (UnicodeError, binascii.Error):
        raise KeyProtectionError("已存密钥格式无效。") from None
    if not _valid_key(plaintext):
        raise KeyProtectionError("已存密钥格式无效。")
    return plaintext
