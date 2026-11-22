using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace DoujieStudio
{
    internal static class Program
    {
        internal static string Sdk;

        [STAThread]
        private static int Main(string[] args)
        {
            try
            {
                try { Console.OutputEncoding = new UTF8Encoding(false); } catch (IOException) { }
                int port = 0, owner = 0;
                bool parent = false, focusOnly = false;
                string readyFile = null;
                foreach (string argument in args)
                {
                    if (argument.StartsWith("--studio-port=", StringComparison.Ordinal))
                        int.TryParse(argument.Substring(14), NumberStyles.None, CultureInfo.InvariantCulture, out port);
                    else if (argument == "--studio-parent") parent = true;
                    else if (argument == "--studio-focus") focusOnly = true;
                    else if (argument.StartsWith("--studio-owner=", StringComparison.Ordinal))
                        int.TryParse(argument.Substring(15), NumberStyles.None, CultureInfo.InvariantCulture, out owner);
                    else if (argument.StartsWith("--studio-ready-file=", StringComparison.Ordinal))
                    {
                        readyFile = argument.Substring(20);
                        if (!Path.IsPathRooted(readyFile)) return 2;
                    }
                }
                if (port < 1 || port > 65535) return 2;
                string instance = "DoujieStudio.WebView2." + WindowsIdentity.GetCurrent().User.Value + "." + port;
                bool first;
                using (var mutex = new Mutex(true, @"Local\" + instance, out first))
                {
                    if (!first || focusOnly)
                    {
                        if (!FocusExisting(instance)) return 2;
                        Mark(readyFile, "focused");
                        return 0;
                    }
                    Sdk = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "sdk");
                    AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs e)
                    {
                        string name = new AssemblyName(e.Name).Name;
                        if (name != "Microsoft.Web.WebView2.Core" && name != "Microsoft.Web.WebView2.Wpf") return null;
                        return Assembly.LoadFrom(Path.Combine(Sdk, name + ".dll"));
                    };
                    return Run(port, instance, parent, owner, readyFile);
                }
            }
            catch (Exception error) { Report("host-start", error); return 1; }
        }

        internal static void Report(string phase, Exception error)
        {
            string entry = "WebView2 " + phase + " " + error.GetType().Name + " HRESULT=0x" +
                error.HResult.ToString("X8", CultureInfo.InvariantCulture);
            Console.Error.WriteLine(entry);
            string file = Environment.GetEnvironmentVariable("DOUJIE_START_LOG");
            if (String.IsNullOrEmpty(file)) return;
            try
            {
                using (var output = new FileStream(file, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
                using (var writer = new StreamWriter(output, new UTF8Encoding(false)))
                    writer.WriteLine(entry);
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }

        // Load the WebView2 types only after the private SDK assembly resolver is installed.
        [MethodImpl(MethodImplOptions.NoInlining)]
        private static int Run(int port, string instance, bool parent, int owner, string readyFile)
        {
            CoreWebView2Environment.SetLoaderDllFolderPath(Sdk);
            return new Studio(port, instance, parent, owner, readyFile).Run();
        }

        internal static void Mark(string file, string status)
        {
            if (file != null) File.WriteAllText(file, status, new UTF8Encoding(false));
        }

        internal static readonly uint FocusMessage = RegisterWindowMessage("DoujieStudio.WebView2.Focus.v1");
        private delegate bool VisitWindow(IntPtr window, IntPtr data);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern uint RegisterWindowMessage(string name);
        [DllImport("user32.dll")] private static extern bool EnumWindows(VisitWindow visit, IntPtr data);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr GetProp(IntPtr window, string name);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] internal static extern bool SetProp(IntPtr window, string name, IntPtr value);
        [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
        [DllImport("user32.dll")] private static extern bool AllowSetForegroundWindow(uint pid);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr SendMessageTimeout(IntPtr window, uint message, IntPtr wParam, IntPtr lParam,
                                                       uint flags, uint timeout, out IntPtr result);

        private static bool FocusExisting(string instance)
        {
            IntPtr target = IntPtr.Zero;
            EnumWindows(delegate(IntPtr w, IntPtr unused)
            {
                if (GetProp(w, instance) == IntPtr.Zero) return true;
                target = w;
                return false;
            }, IntPtr.Zero);
            if (target == IntPtr.Zero || FocusMessage == 0) return false;
            uint pid;
            GetWindowThreadProcessId(target, out pid);
            AllowSetForegroundWindow(pid);
            IntPtr reply;
            return SendMessageTimeout(target, FocusMessage, IntPtr.Zero, IntPtr.Zero, 2, 2200, out reply) != IntPtr.Zero
                && reply == (IntPtr)1;
        }
    }

    internal sealed class Studio
    {
        private readonly Application app = new Application();
        private readonly string origin, instanceTag, readyFile;
        private readonly bool watchParent;
        private readonly int ownerPid;
        private readonly Size portraitSize;
        private Window director, stage;
        private Point? lastStagePosition;
        private CoreWebView2Environment environment;
        private bool directorReady, stageReady, markedReady, closing;

        internal Studio(int port, string instance, bool parent, int owner, string ready)
        {
            origin = "http://127.0.0.1:" + port;
            instanceTag = instance;
            watchParent = parent;
            ownerPid = owner;
            readyFile = ready;
            Rect work = SystemParameters.WorkArea;
            double unit = Math.Max(1, Math.Min(50, Math.Floor(Math.Min(work.Width / 9, work.Height / 16))));
            portraitSize = new Size(9 * unit, 16 * unit);
            app.ShutdownMode = ShutdownMode.OnExplicitShutdown;
        }

        internal int Run()
        {
            app.Startup += Start;
            return app.Run();
        }

        private async void Start(object sender, StartupEventArgs e)
        {
            try
            {
                if (watchParent && ownerPid > 0) new Thread(WatchParentProcess) { IsBackground = true }.Start();
                if (watchParent && (ownerPid == 0 || GetFileType(GetStdHandle(-10)) == 3))
                    new Thread(WatchLauncher) { IsBackground = true }.Start();
                string profile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "DoujieStudio", "WebView2", new Uri(origin).Port.ToString(CultureInfo.InvariantCulture));
                var options = new CoreWebView2EnvironmentOptions();
                options.AdditionalBrowserArguments = "--autoplay-policy=no-user-gesture-required";
                environment = await CoreWebView2Environment.CreateAsync(null, profile, options);
                if (closing) return;
                OpenDirector();
                ShowStage();
            }
            catch (Exception error) { Fail("environment", error); }
        }

        private void WatchLauncher()
        {
            try
            {
                using (var input = new StreamReader(Console.OpenStandardInput()))
                {
                    string line;
                    while ((line = input.ReadLine()) != null && line != "quit") { }
                }
            }
            catch (IOException) { }
            if (!app.Dispatcher.HasShutdownStarted)
                app.Dispatcher.BeginInvoke(new Action(delegate { Exit(0); }));
        }

        [DllImport("kernel32.dll")] private static extern IntPtr GetStdHandle(int name);
        [DllImport("kernel32.dll")] private static extern uint GetFileType(IntPtr handle);

        private void WatchParentProcess()
        {
            try { using (Process owner = Process.GetProcessById(ownerPid)) owner.WaitForExit(); }
            catch (ArgumentException) { /* The launcher already exited. */ }
            catch (Win32Exception error) { Console.Error.WriteLine(error.Message); }
            if (!app.Dispatcher.HasShutdownStarted)
                app.Dispatcher.BeginInvoke(new Action(delegate { Exit(0); }));
        }

        private static void Activate(Window window)
        {
            if (window.WindowState == WindowState.Minimized) window.WindowState = WindowState.Normal;
            window.Show();
            window.Activate();
        }

        private void OpenDirector()
        {
            Rect work = SystemParameters.WorkArea;
            director = new Window {
                Title = "豆姐锐评室 · 导播台", ShowActivated = true, WindowStartupLocation = WindowStartupLocation.Manual,
                Left = Math.Min(work.Right - portraitSize.Width, work.Left + 8),
                Top = Math.Min(work.Bottom - portraitSize.Height, work.Top + 8),
                Width = portraitSize.Width, Height = portraitSize.Height,
                ResizeMode = ResizeMode.CanMinimize, Background = Brushes.FloralWhite
            };
            director.Closed += delegate { director = null; Exit(0); };
            director.SourceInitialized += delegate {
                IntPtr hwnd = new WindowInteropHelper(director).Handle;
                if (!Program.SetProp(hwnd, instanceTag, (IntPtr)1) || Program.FocusMessage == 0)
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                HwndSource.FromHwnd(hwnd).AddHook(OnDirectorMessage);
            };
            app.MainWindow = director;
            StartWindow(director, false);
        }

        private IntPtr OnDirectorMessage(IntPtr hwnd, int message, IntPtr wParam, IntPtr lParam, ref bool handled)
        {
            if ((uint)message != Program.FocusMessage || !directorReady || closing || director == null) return IntPtr.Zero;
            Activate(director);
            handled = true;
            return (IntPtr)1;
        }

        private void ShowStage()
        {
            if (closing) return;
            if (stage != null) { Activate(stage); return; }
            Rect work = SystemParameters.WorkArea;
            stageReady = false;
            stage = new Window {
                Title = "豆姐 · 直播舞台", WindowStyle = WindowStyle.None, ResizeMode = ResizeMode.NoResize,
                WindowStartupLocation = WindowStartupLocation.Manual, ShowActivated = false,
                Width = portraitSize.Width, Height = portraitSize.Height, UseLayoutRounding = true, Background = Brushes.Black
            };
            stage.Left = lastStagePosition.HasValue ? lastStagePosition.Value.X : Math.Max(work.Left, work.Right - stage.Width - 8);
            stage.Top = lastStagePosition.HasValue ? lastStagePosition.Value.Y : Math.Min(work.Bottom - stage.Height, work.Top + 8);
            stage.Closing += delegate(object sender, CancelEventArgs e) {
                lastStagePosition = new Point(((Window)sender).Left, ((Window)sender).Top);
            };
            stage.Closed += delegate { stage = null; stageReady = false; };
            StartWindow(stage, true);
        }

        private async void StartWindow(Window window, bool isStage)
        {
            string url = origin + (isStage ? "/stage.html" : "/");
            var view = new WebView2();
            bool closed = false;
            window.Closed += delegate { closed = true; view.Dispose(); };
            try
            {
                window.Content = view;
                window.Show();
                await view.EnsureCoreWebView2Async(environment);
                if (closed || closing) return;
                CoreWebView2 core = view.CoreWebView2;
                core.Settings.AreDevToolsEnabled = false;
                core.Settings.AreDefaultContextMenusEnabled = false;
                core.Settings.AreBrowserAcceleratorKeysEnabled = false;
                core.Settings.AreDefaultScriptDialogsEnabled = false;
                core.Settings.AreHostObjectsAllowed = false;
                core.Settings.IsStatusBarEnabled = false;
                core.Settings.IsZoomControlEnabled = false;
                core.NewWindowRequested += delegate(object s, CoreWebView2NewWindowRequestedEventArgs a) { a.Handled = true; };
                core.NavigationStarting += delegate(object s, CoreWebView2NavigationStartingEventArgs a) {
                    if (!String.Equals(a.Uri, url, StringComparison.Ordinal)) a.Cancel = true;
                };
                core.FrameNavigationStarting += delegate(object s, CoreWebView2NavigationStartingEventArgs a) { a.Cancel = true; };
                core.LaunchingExternalUriScheme += delegate(object s, CoreWebView2LaunchingExternalUriSchemeEventArgs a) { a.Cancel = true; };
                core.DownloadStarting += delegate(object s, CoreWebView2DownloadStartingEventArgs a) { a.Cancel = true; };
                core.PermissionRequested += delegate(object s, CoreWebView2PermissionRequestedEventArgs a) { a.State = CoreWebView2PermissionState.Deny; };
                core.WebMessageReceived += delegate(object s, CoreWebView2WebMessageReceivedEventArgs a) {
                    if (closing || a.Source != url) return;
                    string action;
                    try { action = a.TryGetWebMessageAsString(); } catch (ArgumentException) { return; }
                    if (isStage && action == "drag") Drag(window);
                    if (!isStage && action == "open-stage")
                    {
                        ShowStage();
                        core.PostWebMessageAsString("stage-shown");
                    }
                };
                await core.AddScriptToExecuteOnDocumentCreatedAsync(isStage ? DragScript : DirectorScript);
                if (closed || closing) return;
                core.NavigationCompleted += delegate(object s, CoreWebView2NavigationCompletedEventArgs a) {
                    if (closed || closing) return;
                    if (!a.IsSuccess || a.HttpStatusCode < 200 || a.HttpStatusCode >= 300) {
                        if ((!isStage && !directorReady) || (isStage && !stageReady))
                            Fail((isStage ? "stage" : "director") + "-navigation WebErrorStatus=" +
                                a.WebErrorStatus + " HTTP=" + a.HttpStatusCode, new IOException());
                        return;
                    }
                    if (core.Source != url) return;
                    if (isStage) stageReady = true; else directorReady = true;
                    if (!markedReady && directorReady && stageReady && stage.IsVisible && director.IsVisible) {
                        try { Program.Mark(readyFile, "ready"); markedReady = true; }
                        catch (Exception error) { Fail("ready-marker", error); }
                    }
                };
                core.Navigate(url);
            }
            catch (Exception error) { if (!closed && !closing) Fail(isStage ? "stage-init" : "director-init", error); }
        }

        private const string DirectorScript = @"
if (window.top === window && location.pathname === '/') {
  let pending;
  Object.defineProperty(window, 'doujieDesktop', {value: Object.freeze({
    openStage() {
      if (pending) return pending;
      pending = new Promise(resolve => {
        const bridge = window.chrome.webview;
        const finish = ok => {
          clearTimeout(timeout); bridge.removeEventListener('message', receive); pending = null; resolve(ok);
        };
        const receive = event => { if (event.data === 'stage-shown') finish(true); };
        const timeout = setTimeout(() => finish(false), 4000);
        bridge.addEventListener('message', receive); bridge.postMessage('open-stage');
      });
      return pending;
    }
  })});
}";

        private const string DragScript = @"
if (window.top === window) addEventListener('pointerdown', event => {
  if (event.isTrusted && event.isPrimary && event.button === 0 &&
      !event.target.closest('button,input,select,textarea,a,[contenteditable=true]')) {
    window.chrome.webview.postMessage('drag');
  }
}, true);";

        [StructLayout(LayoutKind.Sequential)] private struct MousePoint { internal int X; internal int Y; }
        [DllImport("user32.dll")] private static extern bool GetCursorPos(out MousePoint point);
        [DllImport("user32.dll")] private static extern short GetAsyncKeyState(int key);
        [DllImport("user32.dll")] private static extern bool ReleaseCapture();
        [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);

        private static void Drag(Window window)
        {
            MousePoint point;
            if (GetAsyncKeyState(1) >= 0 || !GetCursorPos(out point)) return;
            ReleaseCapture();
            int coordinates = (point.X & 65535) | (point.Y << 16);
            SendMessage(new WindowInteropHelper(window).Handle, 0x00A1, (IntPtr)2, (IntPtr)coordinates);
        }

        private void Fail(string phase, Exception error)
        {
            Program.Report(phase, error);
            Exit(1);
        }

        private void Exit(int code)
        {
            if (closing) return;
            closing = true;
            app.Shutdown(code);
        }
    }
}
