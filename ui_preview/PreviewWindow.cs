// Single WebView2 presentation shell; model/task execution stays in the separate worker.
using System;
using System.IO;
using System.Threading;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Web.WebView2.WinForms;
using Microsoft.Web.WebView2.Core;

class PreviewWindow : Form
{
    static uint activateMessage;
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern uint RegisterWindowMessage(string name);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window, uint message, IntPtr w, IntPtr l);
    [DllImport("shell32.dll", CharSet=CharSet.Unicode)] static extern int SetCurrentProcessExplicitAppUserModelID(string identity);
    readonly WebView2 web = new WebView2();
    PreviewWindow()
    {
        Text = "BGV Scene Control";
        Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        WindowState = FormWindowState.Maximized;
        MinimumSize = new System.Drawing.Size(850,600);
        BackColor = System.Drawing.Color.FromArgb(11,17,27);
        AutoScaleMode = AutoScaleMode.Dpi;
        web.Dock = DockStyle.Fill;
        Controls.Add(web);
        Shown += async delegate {
            try {
                web.CreationProperties = new CoreWebView2CreationProperties { UserDataFolder = Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"profile-bgv") };
                await web.EnsureCoreWebView2Async();
                web.CoreWebView2.Settings.AreHostObjectsAllowed = false;
                web.CoreWebView2.Settings.IsWebMessageEnabled = false;
                web.CoreWebView2.Settings.AreDevToolsEnabled = false;
                web.CoreWebView2.NewWindowRequested += (s,e) => { e.Handled = true; };
                web.CoreWebView2.PermissionRequested += (s,e) => { e.State = CoreWebView2PermissionState.Deny; };
                web.CoreWebView2.NavigationStarting += (s,e) => {
                    Uri uri;
                    if (!Uri.TryCreate(e.Uri,UriKind.Absolute,out uri) || uri.Scheme!="http" || uri.Host!="127.0.0.1" || uri.Port!=8878) e.Cancel=true;
                };
                web.CoreWebView2.Navigate("http://127.0.0.1:8878/");
            } catch(Exception) { MessageBox.Show("Scene Control 未能连接本地界面，请从桌面入口重新打开。",Text); Close(); }
        };
    }
    protected override void WndProc(ref Message message)
    {
        if (message.Msg == activateMessage) {
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Maximized;
            Show(); Activate();
        }
        base.WndProc(ref message);
    }
    [STAThread] static void Main(string[] args)
    {
        // Historical preview/default/--desktop entry points share one window.
        string identity = "BGV.SceneControl";
        SetCurrentProcessExplicitAppUserModelID(identity);
        activateMessage = RegisterWindowMessage(identity+".Activate");
        bool first;
        using (var mutex = new Mutex(true,"Local\\"+identity,out first)) {
            if (!first) { PostMessage(new IntPtr(0xffff),activateMessage,IntPtr.Zero,IntPtr.Zero); return; }
            Application.EnableVisualStyles();
            Application.Run(new PreviewWindow());
            mutex.ReleaseMutex();
        }
    }
}
