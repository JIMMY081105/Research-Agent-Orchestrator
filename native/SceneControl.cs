// C# 5 / .NET Framework 4.8. A real WinForms host; no browser app-mode.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using Microsoft.Win32;

namespace BgvSceneControl
{
    internal sealed class Options
    {
        public bool Smoke, Verify;
        public bool Diagnostic { get { return Smoke || Verify; } }
        public string Id, Error;
        public int Width = 1280, Height = 800, Seconds = 25;
        public string Url = "http://127.0.0.1:8765";
        public static Options Parse(string[] args)
        {
            var result = new Options();
            if (args.Length == 0) return result;
            var values = new Dictionary<string, string>(StringComparer.Ordinal);
            for (int i = 0; i < args.Length; i += 2)
            {
                if (i + 1 == args.Length || values.ContainsKey(args[i])) throw new InvalidDataException("INVALID_ARGUMENTS");
                values.Add(args[i], args[i + 1]);
            }
            Guid id;
            result.Smoke = values.ContainsKey("--smoke"); result.Verify = values.ContainsKey("--verify");
            if (result.Smoke == result.Verify || !Guid.TryParseExact(values[result.Smoke ? "--smoke" : "--verify"], "D", out id) ||
                values.Keys.Any(k => k != (result.Smoke ? "--smoke" : "--verify") && k != "--size" && k != "--seconds" && !(result.Smoke && k == "--url")))
                throw new InvalidDataException("INVALID_DIAGNOSTIC_ARGUMENTS");
            result.Id = id.ToString("D");
            if (result.Smoke)
            {
                result.Url = values.ContainsKey("--url") ? values["--url"] : "http://127.0.0.1:18766";
                if (result.Url != "http://127.0.0.1:18766") throw new InvalidDataException("FIXTURE_URL_REQUIRED");
            }
            if (values.ContainsKey("--size"))
            {
                var match = Regex.Match(values["--size"], @"^([0-9]{3,4})x([0-9]{3,4})$");
                if (!match.Success) throw new InvalidDataException("INVALID_SMOKE_SIZE");
                result.Width = int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture);
                result.Height = int.Parse(match.Groups[2].Value, CultureInfo.InvariantCulture);
                if (result.Width < 800 || result.Width > 2560 || result.Height < 600 || result.Height > 1600)
                    throw new InvalidDataException("INVALID_SMOKE_SIZE");
            }
            if (values.ContainsKey("--seconds") && (!int.TryParse(values["--seconds"], out result.Seconds) || result.Seconds < 10 || result.Seconds > 60))
                throw new InvalidDataException("INVALID_SMOKE_TIMEOUT");
            return result;
        }
    }

    internal static class Files
    {
        internal const string Runtime = @"E:\Github\Building-Generation-Validation\.runtime";
        internal const string Owner = "BGV.Windows.SceneControl.Desktop.v1";
        internal static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 2097152, RecursionLimit = 64 };
        internal static string Safe(string name)
        {
            var path = Path.GetFullPath(name);
            string part = path;
            while (!String.IsNullOrEmpty(part))
            {
                if ((File.Exists(part) || Directory.Exists(part)) && (File.GetAttributes(part) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("REPARSE_PATH");
                var parent = Path.GetDirectoryName(part);
                if (parent == part) break;
                part = parent;
            }
            return path;
        }
        internal static string Hash(byte[] bytes)
        {
            using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }
        internal static string HashFile(string path)
        {
            var info = new FileInfo(Safe(path));
            if (info.Length > 67108864) throw new InvalidDataException("PACKAGE_FILE_TOO_LARGE");
            using (var sha = SHA256.Create()) using (var stream = File.OpenRead(info.FullName))
                return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }
        internal static Dictionary<string, object> Read(string path)
        {
            var file = new FileInfo(Safe(path));
            if (file.Length > 2097152) throw new InvalidDataException("METADATA_TOO_LARGE");
            var result = Json.DeserializeObject(File.ReadAllText(file.FullName, Encoding.UTF8)) as Dictionary<string, object>;
            if (result == null) throw new InvalidDataException("INVALID_METADATA");
            return result;
        }
        internal static void Save(string path, object value)
        {
            path = Safe(path); var directory = Safe(Path.GetDirectoryName(path));
            Directory.CreateDirectory(directory); Safe(directory);
            var temporary = Safe(path + ".tmp");
            File.WriteAllText(temporary, Json.Serialize(value), new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path);
        }
        private static void Inventory(string directory, string root, HashSet<string> found)
        {
            Safe(directory);
            foreach (var child in Directory.GetFileSystemEntries(directory))
            {
                Safe(child);
                if (Directory.Exists(child)) Inventory(child, root, found);
                else
                {
                    var relative = child.Substring(root.Length + 1).Replace('\\', '/');
                    if (relative != "manifest.json") found.Add(relative);
                }
            }
        }
        internal static string VerifyPackage(out string source)
        {
            var executable = Safe(Assembly.GetExecutingAssembly().Location);
            var app = Path.GetDirectoryName(executable); var root = Safe(Path.GetDirectoryName(app));
            var sha = Path.GetFileName(root);
            if (!Regex.IsMatch(sha, "^[0-9a-f]{64}$") || Path.GetFileName(app) != "app" ||
                !String.Equals(root, Path.Combine(Runtime, "desktop", "snapshots", sha), StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("PACKAGE_LOCATION_INVALID");
            var record = Read(Path.Combine(root, "manifest.json"));
            if (!record.ContainsKey("owner") || !Object.Equals(record["owner"], Owner) || !record.ContainsKey("sha256") || !Object.Equals(record["sha256"], sha))
                throw new InvalidDataException("PACKAGE_IDENTITY_INVALID");
            var files = record.ContainsKey("files") ? record["files"] as Dictionary<string, object> : null;
            if (files == null || files.Count == 0 || files.Count > 512) throw new InvalidDataException("PACKAGE_FILESET_INVALID");
            var ordered = new SortedDictionary<string, string>(StringComparer.Ordinal);
            var aliases = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var item in files)
            {
                var name = item.Key; var hash = item.Value as string;
                if (!Regex.IsMatch(name, @"^[A-Za-z0-9_./ -]{1,240}$") || name.StartsWith("/", StringComparison.Ordinal) ||
                    name.Split('/').Any(p => p.Length == 0 || p == "." || p == ".." || p.EndsWith(".", StringComparison.Ordinal) || p.EndsWith(" ", StringComparison.Ordinal)) ||
                    name == "manifest.json" || hash == null || !Regex.IsMatch(hash, "^[0-9a-f]{64}$") || !aliases.Add(name))
                    throw new InvalidDataException("PACKAGE_PATH_INVALID");
                ordered.Add(name, hash);
            }
            var canonical = "{" + String.Join(",", ordered.Select(p => "\"" + p.Key + "\":\"" + p.Value + "\"")) + "}";
            if (Hash(Encoding.UTF8.GetBytes(canonical)) != sha) throw new InvalidDataException("PACKAGE_MANIFEST_CHANGED");
            var found = new HashSet<string>(StringComparer.Ordinal); Inventory(root, root, found);
            if (!found.SetEquals(ordered.Keys) || !ordered.ContainsKey("app/SceneControl.exe") || !ordered.ContainsKey("source/desktop.py"))
                throw new InvalidDataException("PACKAGE_EXTRA_OR_MISSING_FILE");
            foreach (var item in ordered)
                if (HashFile(Path.Combine(root, item.Key.Replace('/', Path.DirectorySeparatorChar))) != item.Value)
                    throw new InvalidDataException("PACKAGE_CONTENT_CHANGED");
            source = Safe(Path.Combine(root, "source")); return sha;
        }
    }

    internal sealed class ControlWindow : Form
    {
        private readonly Options options;
        private readonly Panel loading = new Panel();
        private readonly Label message = new Label(), status = new Label();
        private readonly Button retry = new Button();
        private readonly HttpClient http;
        private readonly System.Windows.Forms.Timer health = new System.Windows.Forms.Timer();
        private readonly System.Windows.Forms.Timer smokeTimer = new System.Windows.Forms.Timer();
        private WebView2 web;
        private TaskCompletionSource<bool> navigationWaiter;
        private string packageSha = "UNVERIFIED", source, phase = "STARTING";
        private bool ensureBusy, recoveryArmed = true, backendAuthorized, captured, closed, healthBusy;
        private int attempts;
        internal int ExitCode;
        internal ControlWindow(Options value)
        {
            options = value;
            Text = "SCENE // CONTROL"; BackColor = Color.FromArgb(5, 9, 16); ForeColor = Color.FromArgb(108, 238, 230);
            try { Icon = System.Drawing.Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location); } catch (Exception) { }
            Font = new Font("Segoe UI", 10); AutoScaleMode = AutoScaleMode.Dpi; MinimumSize = new Size(800, 600);
            StartPosition = FormStartPosition.CenterScreen;
            if (options.Diagnostic) ClientSize = new Size(options.Width, options.Height); else WindowState = FormWindowState.Maximized;
            var header = new Panel { Dock = DockStyle.Top, Height = 38, BackColor = Color.FromArgb(10, 17, 28) };
            header.Controls.Add(new Label { Text = "SCENE // CONTROL    桌面控制台 / 文本分析", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, Padding = new Padding(14, 0, 0, 0) });
            status.Dock = DockStyle.Bottom; status.Height = 25; status.TextAlign = ContentAlignment.MiddleLeft;
            status.Padding = new Padding(12, 0, 0, 0); status.Text = "正在初始化本地窗口…";
            loading.Dock = DockStyle.Fill; loading.BackColor = BackColor;
            message.Dock = DockStyle.Fill; message.Text = "正在验证固定程序包并连接本地系统…"; message.TextAlign = ContentAlignment.MiddleCenter;
            retry.Text = "重试连接"; retry.Dock = DockStyle.Bottom; retry.Height = 42; retry.FlatStyle = FlatStyle.Flat;
            retry.Click += async delegate { recoveryArmed = true; await EnsureWave("用户重试"); };
            loading.Controls.Add(message); loading.Controls.Add(retry);
            Controls.Add(loading); Controls.Add(status); Controls.Add(header);
            var handler = new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false, UseCookies = false };
            http = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(2), MaxResponseContentBufferSize = 8192 };
            health.Interval = 10000; health.Tick += async delegate { await CheckHealth(); };
            smokeTimer.Interval = options.Seconds * 1000; smokeTimer.Tick += delegate { FinishSmokeTimeout(); };
            Shown += async delegate
            {
                if (options.Diagnostic)
                {
                    smokeTimer.Start();
                    try
                    {
                        var evidence = Files.Safe(Path.Combine(Files.Runtime, "desktop", "verification", options.Id));
                        if (File.Exists(Path.Combine(evidence, "native.json")) || File.Exists(Path.Combine(evidence, "content.png")))
                        { Fail("该验收 ID 已有证据；旧记录保留，请使用新的 ID。"); return; }
                    }
                    catch (Exception) { Fail("验收证据路径校验失败；未执行后台操作。"); return; }
                }
                if (options.Error != null) { Fail(options.Error); return; }
                if (options.Smoke) { backendAuthorized = true; try { await InitializeWeb(); } catch (Exception) { Fail("WebView2 测试初始化失败；等待自动退出。"); } }
                else { WriteWindow(); await EnsureWave("启动"); health.Start(); }
            };
            ResizeEnd += delegate { if (!options.Diagnostic) WriteWindow(); };
            FormClosed += delegate { closed = true; if (navigationWaiter != null) navigationWaiter.TrySetResult(false); health.Stop(); smokeTimer.Stop(); SystemEvents.PowerModeChanged -= PowerChanged; http.Dispose(); if (!options.Diagnostic) { phase = "CLOSED"; WriteWindow(); } };
            SystemEvents.PowerModeChanged += PowerChanged;
        }
        private void PowerChanged(object sender, PowerModeChangedEventArgs args)
        {
            if (args.Mode == PowerModes.Resume && !options.Diagnostic && !closed && IsHandleCreated)
                BeginInvoke(new Action(async delegate { recoveryArmed = true; await EnsureWave("睡醒后核对"); }));
        }
        internal void BringToFrontOwned()
        {
            if (closed) return;
            if (WindowState == FormWindowState.Minimized) WindowState = options.Diagnostic ? FormWindowState.Normal : FormWindowState.Maximized;
            Show(); Activate(); Native.SetForegroundWindow(Handle);
        }
        private void SetStatus(string text) { if (!closed) { status.Text = text; message.Text = text; } }
        private void Fail(string text) { phase = "UNAVAILABLE"; ExitCode = 2; SetStatus(text); loading.Visible = true; loading.BringToFront(); WriteWindow(); }
        private void WriteWindow()
        {
            if (options.Diagnostic || !IsHandleCreated) return;
            try
            {
                var process = Process.GetCurrentProcess();
                Files.Save(Path.Combine(Files.Runtime, "desktop", "window.json"), new {
                    owner = Files.Owner, pid = process.Id, birth = process.StartTime.ToUniversalTime().ToFileTimeUtc().ToString(CultureInfo.InvariantCulture),
                    sha256 = packageSha, hwnd = Handle.ToInt64().ToString(CultureInfo.InvariantCulture), state = phase,
                    observed_at = DateTime.UtcNow.ToString("o"), client_width = ClientSize.Width, client_height = ClientSize.Height,
                    dpi = Native.GetDpi(Handle), ensure_attempts = attempts, read_only = true, task_submission_enabled = true, model_calls = 0 });
            }
            catch (IOException) { SetStatus("本地窗口证据暂不可写；监控未修改任何研究任务。"); }
            catch (UnauthorizedAccessException) { SetStatus("本地窗口证据权限不足。"); }
            catch (InvalidDataException) { SetStatus("窗口证据路径校验失败。"); }
        }
        private async Task EnsureWave(string reason)
        {
            if (closed || ensureBusy || options.Smoke || !recoveryArmed) return;
            ensureBusy = true; recoveryArmed = false; retry.Enabled = false;
            try
            {
                if (packageSha == "UNVERIFIED")
                {
                    string verifiedSource = null;
                    packageSha = await Task.Run(() => Files.VerifyPackage(out verifiedSource)); source = verifiedSource;
                }
                for (int i = 0; i < 3 && !closed; i++)
                {
                    attempts++; phase = "CONNECTING"; SetStatus(reason + " · 连接本地服务 " + (i + 1) + "/3…"); WriteWindow();
                    var ready = await RunEnsure();
                    if (ready)
                    {
                        backendAuthorized = true;
                        if (await InitializeWeb()) { ExitCode = 0; recoveryArmed = true; return; }
                    }
                    if (i < 2) await Task.Delay(2000 * (i + 1));
                }
                Fail("本地服务暂未就绪。已停止自动重试，可稍后点击“重试连接”；现有任务保持原状。");
            }
            catch (Exception) { Fail("本地程序包或 WebView2 初始化未通过，请检查本地部署证据后重试。"); }
            finally { ensureBusy = false; if (!closed) retry.Enabled = true; }
        }
        private static async Task<string> ReadBounded(StreamReader reader)
        {
            var result = new StringBuilder(); var buffer = new char[1024]; int length;
            while ((length = await reader.ReadAsync(buffer, 0, buffer.Length)) != 0)
            {
                if (result.Length + length > 8192) throw new InvalidDataException("ENSURE_OUTPUT_LIMIT");
                result.Append(buffer, 0, length);
            }
            return result.ToString();
        }
        private async Task<bool> RunEnsure()
        {
            var info = new ProcessStartInfo { FileName = @"C:\Python312\python.exe", UseShellExecute = false,
                CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden, RedirectStandardOutput = true, RedirectStandardError = true,
                WorkingDirectory = source, Arguments = "-B \"" + Path.Combine(source, "desktop.py") + "\" ensure --root \"" + source +
                    "\" --runtime \"" + Files.Runtime + "\" --expected-hash " + packageSha };
            using (var process = new Process { StartInfo = info })
            {
                if (!process.Start()) return false;
                var birth = process.StartTime.ToUniversalTime().ToFileTimeUtc();
                var output = ReadBounded(process.StandardOutput); var errors = ReadBounded(process.StandardError);
                bool exited = await Task.Run(() => process.WaitForExit(35000));
                if (!exited)
                {
                    // Only our short-lived ensure helper, never the scheduled UI service or a research process.
                    if (!process.HasExited && process.StartTime.ToUniversalTime().ToFileTimeUtc() == birth) process.Kill();
                    return false;
                }
                string text = await output; await errors;
                if (process.ExitCode != 0 || text.Length > 8192) return false;
                var value = Files.Json.DeserializeObject(text.Trim()) as Dictionary<string, object>;
                return value != null && value.ContainsKey("state") && Object.Equals(value["state"], "READY") &&
                    value.ContainsKey("url") && Object.Equals(value["url"], "http://127.0.0.1:8765");
            }
        }
        private bool Allowed(string value)
        {
            return AllowedResource(value, "GET");
        }
        private bool AllowedResource(string value, string method)
        {
            Uri uri, target;
            if (!Uri.TryCreate(value, UriKind.Absolute, out uri) || !Uri.TryCreate(options.Url, UriKind.Absolute, out target) ||
                uri.Scheme != "http" || uri.Host != "127.0.0.1" || uri.Port != target.Port || uri.UserInfo.Length != 0 || uri.Query.Length != 0)
                return false;
            var path = uri.AbsolutePath;
            // The backend independently enforces Origin/CSRF, schemas and approved actions.
            // This host exposes only these fixed local task endpoints, never arbitrary URLs.
            if (method == "POST") return new[] { "/api/tasks", "/api/worker/turns", "/api/worker/approval", "/api/worker/cancel" }.Contains(path);
            if (method != "GET" && method != "HEAD") return false;
            if (new[] { "/", "/api/health", "/api/status", "/assets/dashboard.css", "/assets/dashboard.js", "/assets/worker.css", "/assets/worker.js", "/assets/david.jpg", "/assets/lucy.jpg", "/assets/david.mp4", "/assets/lucy.mp4" }.Contains(path))
                return true;
            if (method != "GET") return false;
            if (new[] { "/api/composer", "/api/worker/capabilities", "/api/worker/status" }.Contains(path)) return true;
            const string workerPrefix = "/api/worker/status/";
            if (path.StartsWith(workerPrefix, StringComparison.Ordinal))
            {
                var session = path.Substring(workerPrefix.Length);
                Guid sessionId;
                return Guid.TryParseExact(session, "D", out sessionId) && sessionId.ToString("D") == session;
            }
            const string prefix = "/api/tasks/";
            if (!path.StartsWith(prefix, StringComparison.Ordinal)) return false;
            var taskId = path.Substring(prefix.Length);
            Guid parsed;
            return Guid.TryParseExact(taskId, "D", out parsed) && parsed.ToString("D") == taskId;
        }
        private async Task<bool> NavigateReady()
        {
            if (closed || web == null || web.CoreWebView2 == null) return false;
            var waiter = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            navigationWaiter = waiter;
            web.CoreWebView2.Navigate(options.Url + "/");
            var completed = await Task.WhenAny(waiter.Task, Task.Delay(12000));
            if (Object.ReferenceEquals(navigationWaiter, waiter)) navigationWaiter = null;
            if (completed == waiter.Task) return !closed && await waiter.Task;
            if (!closed) Fail("本地页面加载超时；只会执行本轮剩余的有界恢复。");
            return false;
        }
        private async Task<bool> InitializeWeb()
        {
            if (closed || !backendAuthorized) return false;
            if (web != null && web.CoreWebView2 != null) return await NavigateReady();
            if (web != null) { Controls.Remove(web); web.Dispose(); web = null; }
            var profile = options.Diagnostic ? Path.Combine(Files.Runtime, "desktop", "verification", options.Id, "webview") :
                Path.Combine(Files.Runtime, "desktop", "webview", packageSha);
            Files.Safe(profile); Directory.CreateDirectory(profile); Files.Safe(profile);
            var environment = await CoreWebView2Environment.CreateAsync(null, profile, null);
            if (closed) return false;
            web = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = BackColor };
            Controls.Add(web); loading.Visible = true; loading.BringToFront(); await web.EnsureCoreWebView2Async(environment);
            var core = web.CoreWebView2; var settings = core.Settings;
            settings.AreHostObjectsAllowed = false; settings.IsWebMessageEnabled = false;
            settings.AreDevToolsEnabled = false; settings.AreDefaultContextMenusEnabled = false;
            settings.IsPasswordAutosaveEnabled = false; settings.IsGeneralAutofillEnabled = false;
            settings.AreBrowserAcceleratorKeysEnabled = false; settings.IsBuiltInErrorPageEnabled = false;
            core.PermissionRequested += delegate(object sender, CoreWebView2PermissionRequestedEventArgs e) { e.State = CoreWebView2PermissionState.Deny; };
            core.DownloadStarting += delegate(object sender, CoreWebView2DownloadStartingEventArgs e) { e.Cancel = true; };
            core.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e) { e.Handled = true; };
            core.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) { if (!Allowed(e.Uri)) { e.Cancel = true; SetStatus("已阻止非本地页面导航。"); } };
            core.FrameNavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) { if (!Allowed(e.Uri)) e.Cancel = true; };
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += delegate(object sender, CoreWebView2WebResourceRequestedEventArgs e)
            {
                if (!AllowedResource(e.Request.Uri, e.Request.Method))
                    e.Response = environment.CreateWebResourceResponse(new MemoryStream(Encoding.UTF8.GetBytes("LOCAL_READ_ONLY")), 403, "Forbidden", "Content-Type: text/plain");
            };
            core.NavigationCompleted += async delegate(object sender, CoreWebView2NavigationCompletedEventArgs e)
            {
                if (closed) return;
                if (!e.IsSuccess || e.HttpStatusCode >= 400)
                {
                    Fail("本地页面连接失败；未停止或重启任何研究进程。");
                    if (navigationWaiter != null) navigationWaiter.TrySetResult(false);
                    if (!options.Smoke && !ensureBusy && recoveryArmed) await EnsureWave("页面连接失败");
                    return;
                }
                loading.Visible = false; web.BringToFront(); phase = "READY"; recoveryArmed = true; ExitCode = 0;
                SetStatus("已连接本地控制台 · 英国时间 / UTC 账本日"); WriteWindow();
                if (navigationWaiter != null) navigationWaiter.TrySetResult(true);
                if (options.Diagnostic && !captured) { captured = true; await CaptureSmoke(); }
            };
            return await NavigateReady();
        }
        private async Task CheckHealth()
        {
            if (closed || healthBusy || ensureBusy || options.Smoke) return;
            healthBusy = true;
            bool needsRecovery = false;
            try
            {
                using (var response = await http.GetAsync(options.Url + "/api/health"))
                {
                    var value = Files.Json.DeserializeObject(await response.Content.ReadAsStringAsync()) as Dictionary<string, object>;
                    if (!response.IsSuccessStatusCode || value == null || !value.ContainsKey("owner") ||
                        !Object.Equals(value["owner"], "BGV.Windows.ResearchOps.UI.v1") || !value.ContainsKey("read_only") || !Object.Equals(value["read_only"], true))
                        throw new InvalidDataException("HEALTH_UNVERIFIED");
                }
                if (phase == "READY") { recoveryArmed = true; SetStatus("本地监控在线 · 文本任务需主动提交 · 英国时间 / UTC 账本日"); }
                else if (recoveryArmed) needsRecovery = true;
            }
            catch (Exception) { Fail("本地连接暂不可用；原数据可能过期，可使用原生“重试连接”。现有任务未被干预。"); needsRecovery = true; }
            finally { healthBusy = false; }
            if (needsRecovery) await EnsureWave("连接恢复核对");
        }
        private const string Probe = @"(function(){
var worker=document.getElementById('workerForm'), workerVisible=worker&&!worker.hidden;
var selectors={mission:'.cy-mission',gpu:'.cy-gpu',codex:'.cy-code',claude:'.cy-claude',connection:'[data-connection]',refresh:'[data-refresh]',runtime:'[data-runtime]',gpuState:'[data-gpu-state]',gpuUtil:'[data-gpu-util]',codexState:'[data-code-state]',claudeState:'[data-claude-state]',observed:'[data-observed]',gpuObserved:'[data-gpu-observed]',composerPrompt:workerVisible?'#workerPrompt':'#composerPrompt',composerSubmit:workerVisible?'#workerSubmit':'#composerSubmit'};
var result={viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio},document:{width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight,clientWidth:document.documentElement.clientWidth,clientHeight:document.documentElement.clientHeight},elements:{},avatars:{},ukTime:{browserTimeZone:Intl.DateTimeFormat().resolvedOptions().timeZone,expectedDisplayZone:'Europe/London'}};
function rect(element){var r=element.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};}
Object.keys(selectors).forEach(function(key){
    var element=document.querySelector(selectors[key]);
    if(!element){result.elements[key]={found:false,visible:false};return;}
    var r=rect(element),s=getComputedStyle(element);
    result.elements[key]={found:true,visible:r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none',insideViewport:r.x>=-1&&r.y>=-1&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1,rect:r};
    if(key==='observed'||key==='gpuObserved')result.ukTime[key]=element.textContent.slice(0,200);
});
['david','lucy'].forEach(function(key){
    var frame=document.querySelector('[data-avatar='+key+']'),image=document.querySelector('[data-avatar-source='+key+']');
    if(!frame||!image){result.avatars[key]={found:false,checks:{loaded:false}};return;}
    var fs=getComputedStyle(frame),is=getComputedStyle(image),fw=frame.clientWidth-parseFloat(fs.paddingLeft||0)-parseFloat(fs.paddingRight||0),fh=frame.clientHeight-parseFloat(fs.paddingTop||0)-parseFloat(fs.paddingBottom||0);
    var iw=parseFloat(is.width),ih=parseFloat(is.height),nw=image.naturalWidth,nh=image.naturalHeight;
    var loaded=image.complete&&nw>0&&nh>0,cellAspect=loaded?(nw/3)/(nh/2):0;
    var entry={found:true,loaded:loaded,naturalWidth:nw,naturalHeight:nh,gridColumns:3,gridRows:2,objectFit:is.objectFit,overflowX:fs.overflowX,overflowY:fs.overflowY,src:image.getAttribute('src'),frame:rect(frame),image:rect(image),frameContentWidth:fw,frameContentHeight:fh,imageContentWidth:iw,imageContentHeight:ih};
    entry.checks={loaded:loaded,frameMatchesCellAspect:loaded&&fw>0&&fh>0&&Math.abs(fw/fh-cellAspect)<=0.02,spriteMatchesNaturalAspect:loaded&&iw>0&&ih>0&&Math.abs(iw/ih-nw/nh)<=0.02,singleCellFitsFrame:fw>0&&fh>0&&Math.abs(iw/3-fw)<=1&&Math.abs(ih/2-fh)<=1,frameClipsSprite:['clip','hidden'].indexOf(fs.overflowX)>=0&&['clip','hidden'].indexOf(fs.overflowY)>=0,objectFitPreservesRatio:is.objectFit==='contain',sourceFixed:entry.src==='/assets/'+key+'.jpg'};
    result.avatars[key]=entry;
    var clip=document.querySelector('[data-avatar-video='+key+']');
    if(clip){var cs=getComputedStyle(clip);entry.video={src:clip.getAttribute('src'),readyState:clip.readyState,width:clip.videoWidth,height:clip.videoHeight,currentTime:clip.currentTime,muted:clip.muted,loop:clip.loop,paused:clip.paused,playbackRate:clip.playbackRate,objectFit:cs.objectFit,opacity:parseFloat(cs.opacity),rect:rect(clip),error:clip.error?clip.error.code:null};}
});
var panels=['mission','gpu','codex','claude'],critical=['connection','refresh','runtime','gpuState','gpuUtil','codexState','claudeState','observed','gpuObserved','composerPrompt','composerSubmit'];
result.panels={};panels.forEach(function(k){var e=result.elements[k];result.panels[k]=Object.assign({},e.rect||{},{visible:e.visible,insideViewport:e.insideViewport});});
result.checks={fourPanelsVisible:panels.every(function(k){return result.elements[k].visible;}),fourPanelsInsideViewport:panels.every(function(k){return result.elements[k].insideViewport;}),criticalElementsVisible:critical.every(function(k){return result.elements[k].visible&&result.elements[k].insideViewport;}),noPageVerticalScroll:result.document.height<=innerHeight+1,noPageHorizontalScroll:result.document.width<=innerWidth+1,ukTimeLabelPresent:/\b(BST|GMT)\b/.test((result.ukTime.observed||'')+' '+(result.ukTime.gpuObserved||'')),avatarProportionsCorrect:['david','lucy'].every(function(k){var entry=result.avatars[k];return entry.found&&Object.keys(entry.checks).every(function(c){return entry.checks[c]===true;});})};
return result;})()";
        private sealed class CaptureWindowState
        {
            internal int ClientWidth, ClientHeight, WebWidth, WebHeight, FormWidth, FormHeight;
            internal bool Visible, Normal, Minimized, WebVisible;
            internal bool Usable
            {
                get { return Visible && Normal && !Minimized && WebVisible && ClientWidth > 0 && ClientHeight > 0 && WebWidth > 0 && WebHeight > 0 && FormWidth > 0 && FormHeight > 0; }
            }
            internal bool SameGeometry(CaptureWindowState other)
            {
                return other != null && ClientWidth == other.ClientWidth && ClientHeight == other.ClientHeight &&
                    WebWidth == other.WebWidth && WebHeight == other.WebHeight && FormWidth == other.FormWidth && FormHeight == other.FormHeight;
            }
        }
        private CaptureWindowState ObserveCaptureWindow()
        {
            var result = new CaptureWindowState();
            if (closed || IsDisposed || Disposing || !IsHandleCreated) return result;
            Size actual;
            if (Native.TryClientSize(Handle, out actual)) { result.ClientWidth = actual.Width; result.ClientHeight = actual.Height; }
            result.FormWidth = ClientSize.Width; result.FormHeight = ClientSize.Height;
            result.Visible = Visible && Native.IsWindowVisible(Handle);
            result.Minimized = WindowState == FormWindowState.Minimized || Native.IsIconic(Handle);
            result.Normal = WindowState == FormWindowState.Normal;
            if (web != null && !web.IsDisposed)
            {
                result.WebWidth = web.ClientSize.Width; result.WebHeight = web.ClientSize.Height;
                result.WebVisible = web.Visible;
            }
            return result;
        }
        private async Task<bool> PrepareCaptureWindow()
        {
            if (!options.Diagnostic || closed || IsDisposed || !IsHandleCreated) return false;
            // Restore only this new diagnostic window. The installed app/service is untouched.
            if (WindowState != FormWindowState.Normal) WindowState = FormWindowState.Normal;
            BringToFrontOwned();
            CaptureWindowState previous = null;
            int stable = 0;
            for (int i = 0; i < 10; i++)
            {
                await Task.Delay(150);
                if (closed) return false;
                var current = ObserveCaptureWindow();
                stable = current.Usable && previous != null && previous.Usable && current.SameGeometry(previous) ? stable + 1 : 0;
                if (stable >= 2) return true;
                previous = current;
            }
            return false;
        }
        private void SaveCaptureFailure(string reason)
        {
            try
            {
                var path = Files.Safe(Path.Combine(Files.Runtime, "desktop", "verification", options.Id, "native.json"));
                if (File.Exists(path)) return; // Preserve timeout/earlier evidence rather than rewriting it.
                var dimensions = ObserveCaptureWindow();
                Files.Save(path, new { schema = 1, owner = Files.Owner, run_id = options.Id, verification_id = options.Id,
                    scope = options.Smoke ? "FIXTURE_LAYOUT_ONLY" : "INSTALLED_NATIVE_SERVICE", package_sha256 = options.Smoke ? null : packageSha,
                    success = false, captured = false, reason = reason, observed_at = DateTime.UtcNow.ToString("o"),
                    client_width = dimensions.ClientWidth, client_height = dimensions.ClientHeight,
                    window_visible = dimensions.Visible, window_normal = dimensions.Normal, window_minimized = dimensions.Minimized,
                    model_calls = 0, ensure_calls = attempts, scheduled_task_operations = options.Smoke ? (object)0 : "DELEGATED_TO_VERIFIED_ENSURE" });
            }
            catch (Exception) { }
        }
        private async Task CaptureSmoke()
        {
            try
            {
                await Task.Delay(2500); if (closed) return;
                if (!await PrepareCaptureWindow()) throw new InvalidDataException("NATIVE_WINDOW_NOT_STABLE");
                var beforeProbe = ObserveCaptureWindow();
                var text = await web.CoreWebView2.ExecuteScriptAsync(Probe);
                if (closed) return;
                var beforeCapture = ObserveCaptureWindow();
                var layout = Files.Json.DeserializeObject(text) as Dictionary<string, object>;
                // Only this new diagnostic window is exercised; no service or task action.
                const string avatarSampler = @"window.__bgvAvatarSample=function(){var r={};document.querySelectorAll('[data-avatar-video]').forEach(function(v){r[v.dataset.avatarVideo]={frames:v.getVideoPlaybackQuality().totalVideoFrames,paused:v.paused,time:v.currentTime};});return r;};window.__bgvAvatarA=window.__bgvAvatarSample();";
                await web.CoreWebView2.ExecuteScriptAsync(avatarSampler);
                await Task.Delay(350); if (closed) return;
                await web.CoreWebView2.ExecuteScriptAsync("window.__bgvAvatarB=window.__bgvAvatarSample();document.querySelector('[data-pause]').click();");
                await Task.Delay(150); if (closed) return;
                await web.CoreWebView2.ExecuteScriptAsync("window.__bgvAvatarC=window.__bgvAvatarSample();");
                await Task.Delay(300); if (closed) return;
                await web.CoreWebView2.ExecuteScriptAsync("window.__bgvAvatarD=window.__bgvAvatarSample();document.querySelector('[data-pause]').click();");
                await Task.Delay(350); if (closed) return;
                var videoText = await web.CoreWebView2.ExecuteScriptAsync(@"(function(){var e=window.__bgvAvatarSample(),r={};['david','lucy'].forEach(function(k){var a=window.__bgvAvatarA[k],b=window.__bgvAvatarB[k],c=window.__bgvAvatarC[k],d=window.__bgvAvatarD[k];r[k]={advanced:!!a&&!!b&&!a.paused&&!b.paused&&b.frames>a.frames,pausedHeld:!!c&&!!d&&c.paused&&d.paused&&Math.abs(d.time-c.time)<0.02,resumed:!!d&&!!e[k]&&!e[k].paused&&e[k].frames>d.frames};});return r;})()");
                var avatarMotion = Files.Json.DeserializeObject(videoText) as Dictionary<string, object>;
                if (layout != null) layout["avatarMotion"] = avatarMotion;
                bool videosPassed = avatarMotion != null && avatarMotion.Count == 2 && avatarMotion.Values.All(v => {
                    var item = v as Dictionary<string, object>;
                    return item != null && item.Count == 3 && item.Values.All(x => Object.Equals(x, true));
                });
                var checks = layout == null || !layout.ContainsKey("checks") ? null : layout["checks"] as Dictionary<string, object>;
                bool layoutPassed = checks != null && checks.Count == 7 && checks.Values.All(v => Object.Equals(v, true));
                var document = layout == null ? null : layout["document"] as Dictionary<string, object>;
                var clock = layout == null ? null : layout["ukTime"] as Dictionary<string, object>;
                var elements = layout == null ? null : layout["elements"] as Dictionary<string, object>;
                var critical = new Dictionary<string, object>(StringComparer.Ordinal);
                foreach (var key in new[] { "connection", "refresh", "runtime", "gpuState", "gpuUtil", "codexState", "claudeState", "observed", "gpuObserved", "composerPrompt", "composerSubmit" })
                    if (elements != null && elements.ContainsKey(key)) critical.Add(key, elements[key]);
                var process = Process.GetCurrentProcess();
                string sourceHash = null;
                if (options.Verify)
                {
                    var manifest = Files.Read(Path.Combine(Path.GetDirectoryName(source), "manifest.json"));
                    sourceHash = manifest.ContainsKey("source_sha256") ? manifest["source_sha256"] as string : null;
                    if (sourceHash == null || !Regex.IsMatch(sourceHash, "^[0-9a-f]{64}$")) throw new InvalidDataException("SOURCE_BINDING_UNVERIFIED");
                }
                var directory = Files.Safe(Path.Combine(Files.Runtime, "desktop", "verification", options.Id));
                Directory.CreateDirectory(directory);
                using (var file = new FileStream(Files.Safe(Path.Combine(directory, "content.png")), FileMode.CreateNew, FileAccess.Write))
                    await web.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, file);
                if (closed) return;
                var afterCapture = ObserveCaptureWindow();
                var nativeChecks = new Dictionary<string, object> {
                    { "visible_normal_before_probe", beforeProbe.Usable },
                    { "visible_normal_before_capture", beforeCapture.Usable },
                    { "visible_normal_after_capture", afterCapture.Usable },
                    { "geometry_stable_during_probe", beforeProbe.SameGeometry(beforeCapture) },
                    { "geometry_stable_during_capture", beforeCapture.SameGeometry(afterCapture) }
                };
                bool passed = layoutPassed && videosPassed && nativeChecks.Values.All(v => Object.Equals(v, true));
                Files.Save(Path.Combine(directory, "native.json"), new { schema = 1, owner = Files.Owner, run_id = options.Id,
                    app_path = Assembly.GetExecutingAssembly().Location, process_birth = process.StartTime.ToUniversalTime().ToFileTimeUtc().ToString(CultureInfo.InvariantCulture),
                    source_sha256 = sourceHash, bundle_sha256 = options.Smoke ? null : packageSha, smoke_id = options.Smoke ? options.Id : null,
                    verification_id = options.Id, scope = options.Smoke ? "FIXTURE_LAYOUT_ONLY" : "INSTALLED_NATIVE_SERVICE",
                    mode = options.Smoke ? "FIXED_LOCAL_FIXTURE_ONLY" : "INSTALLED_NATIVE_SERVICE", package_sha256 = options.Smoke ? null : packageSha,
                    success = passed, captured = true, checks = checks, native_checks = nativeChecks, observed_at = DateTime.UtcNow.ToString("o"), pid = Process.GetCurrentProcess().Id,
                    native_window_handle = Handle.ToInt64().ToString(CultureInfo.InvariantCulture), title = Text,
                    hwnd = Handle.ToInt64().ToString(CultureInfo.InvariantCulture), dpi = Native.GetDpi(Handle),
                    client_width = afterCapture.ClientWidth, client_height = afterCapture.ClientHeight,
                    winforms_client_width = afterCapture.FormWidth, winforms_client_height = afterCapture.FormHeight,
                    webview_width = afterCapture.WebWidth, webview_height = afterCapture.WebHeight,
                    window_visible = afterCapture.Visible, window_normal = afterCapture.Normal, window_minimized = afterCapture.Minimized,
                    layout = layout, url = options.Url,
                    viewport = layout == null ? null : layout["viewport"], panels = layout == null ? null : layout["panels"],
                    document_scroll_height = document == null ? null : document["height"], document_client_height = document == null ? null : document["clientHeight"],
                    critical_elements = critical, uk_time = clock,
                    time_text = clock == null ? "" : (clock.ContainsKey("observed") ? clock["observed"] : "") + " · " + (clock.ContainsKey("gpuObserved") ? clock["gpuObserved"] : ""),
                    model_calls = 0, ensure_calls = attempts, scheduled_task_operations = options.Smoke ? (object)0 : "DELEGATED_TO_VERIFIED_ENSURE" });
                ExitCode = passed ? 0 : 2; SetStatus(passed ? "桌面原生取证通过；窗口将在测试时限内自动关闭。" : "桌面布局或英国时间检查未通过；已保存真实失败证据。");
            }
            catch (Exception error)
            {
                ExitCode = 2; SetStatus("桌面测试取证失败；未操作研究任务。");
                SaveCaptureFailure(error is InvalidDataException && error.Message == "NATIVE_WINDOW_NOT_STABLE" ? "NATIVE_WINDOW_NOT_STABLE" : "DIAGNOSTIC_CAPTURE_FAILED");
            }
        }
        private void FinishSmokeTimeout()
        {
            smokeTimer.Stop();
            var path = Path.Combine(Files.Runtime, "desktop", "verification", options.Id, "native.json");
            if (!File.Exists(path))
            {
                ExitCode = 2;
                try { Files.Save(path, new { owner = Files.Owner, verification_id = options.Id,
                    scope = options.Smoke ? "FIXTURE_LAYOUT_ONLY" : "INSTALLED_NATIVE_SERVICE", package_sha256 = options.Smoke ? null : packageSha,
                    success = false, captured = false, reason = "DIAGNOSTIC_TIMEOUT_OR_CAPTURE_FAILED", observed_at = DateTime.UtcNow.ToString("o"),
                    model_calls = 0, ensure_calls = attempts, scheduled_task_operations = options.Smoke ? (object)0 : "DELEGATED_TO_VERIFIED_ENSURE" }); }
                catch (Exception) { }
            }
            Close();
        }
    }

    internal static class Native
    {
        [StructLayout(LayoutKind.Sequential)] private struct ClientRect { internal int Left, Top, Right, Bottom; }
        [DllImport("user32.dll")] internal static extern bool SetForegroundWindow(IntPtr window);
        [DllImport("user32.dll")] internal static extern bool IsWindowVisible(IntPtr window);
        [DllImport("user32.dll")] internal static extern bool IsIconic(IntPtr window);
        [DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr window, out ClientRect rectangle);
        [DllImport("user32.dll")] private static extern bool SetProcessDpiAwarenessContext(IntPtr value);
        [DllImport("user32.dll")] private static extern uint GetDpiForWindow(IntPtr window);
        [DllImport("shell32.dll", CharSet = CharSet.Unicode)] private static extern int SetCurrentProcessExplicitAppUserModelID(string value);
        internal static uint GetDpi(IntPtr window) { try { return GetDpiForWindow(window); } catch (EntryPointNotFoundException) { return 96; } }
        internal static bool TryClientSize(IntPtr window, out Size size)
        {
            ClientRect rectangle;
            if (!GetClientRect(window, out rectangle)) { size = Size.Empty; return false; }
            size = new Size(rectangle.Right - rectangle.Left, rectangle.Bottom - rectangle.Top);
            return size.Width > 0 && size.Height > 0;
        }
        [STAThread]
        private static int Main(string[] args)
        {
            try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch (EntryPointNotFoundException) { }
            SetCurrentProcessExplicitAppUserModelID("BGV.SceneControl");
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            Options options;
            try { options = Options.Parse(args); } catch (Exception) { options = new Options { Error = "启动参数无效；没有执行任何后台操作。" }; }
            string sid = WindowsIdentity.GetCurrent().User.Value;
            string suffix = sid + (options.Smoke ? ".Smoke." + options.Id : options.Verify ? ".Verify." + options.Id : "");
            bool created;
            using (var mutex = new Mutex(false, @"Local\BGV.SceneControl.Desktop." + suffix, out created))
            {
                string eventName = @"Local\BGV.SceneControl.Desktop.Activate." + suffix;
                if (!created)
                {
                    for (int i = 0; i < 5; i++)
                    {
                        try { using (var existing = EventWaitHandle.OpenExisting(eventName)) existing.Set(); return 0; }
                        catch (WaitHandleCannotBeOpenedException) { Thread.Sleep(100); }
                    }
                    return 2;
                }
                using (var signal = new EventWaitHandle(false, EventResetMode.AutoReset, eventName))
                using (var window = new ControlWindow(options))
                {
                    var registration = ThreadPool.RegisterWaitForSingleObject(signal, delegate {
                        if (!window.IsDisposed && window.IsHandleCreated) try { window.BeginInvoke(new Action(window.BringToFrontOwned)); } catch (InvalidOperationException) { }
                    }, null, Timeout.Infinite, false);
                    Application.Run(window); registration.Unregister(null); return window.ExitCode;
                }
            }
        }
    }
}
