// Presentation-only WebView2 shell. No task/model bridge or production connection.
using System;
using System.IO;
using System.Windows.Forms;
using Microsoft.Web.WebView2.WinForms;
using Microsoft.Web.WebView2.Core;

class PreviewWindow : Form
{
    readonly WebView2 web = new WebView2();
    PreviewWindow()
    {
        Text = "Scene Control · UI Preview";
        WindowState = FormWindowState.Maximized;
        MinimumSize = new System.Drawing.Size(850,600);
        BackColor = System.Drawing.Color.FromArgb(11,17,27);
        AutoScaleMode = AutoScaleMode.Dpi;
        web.Dock = DockStyle.Fill;
        Controls.Add(web);
        Shown += async delegate {
            try {
                web.CreationProperties = new CoreWebView2CreationProperties { UserDataFolder = Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"profile") };
                await web.EnsureCoreWebView2Async();
                web.CoreWebView2.Settings.AreHostObjectsAllowed = false;
                web.CoreWebView2.Settings.IsWebMessageEnabled = false;
                web.CoreWebView2.Settings.AreDevToolsEnabled = false;
                web.CoreWebView2.NewWindowRequested += (s,e) => { e.Handled = true; };
                web.CoreWebView2.PermissionRequested += (s,e) => { e.State = CoreWebView2PermissionState.Deny; };
                web.CoreWebView2.NavigationStarting += (s,e) => {
                    Uri uri;
                    if (!Uri.TryCreate(e.Uri,UriKind.Absolute,out uri) || uri.Scheme!="http" || uri.Host!="127.0.0.1" || uri.Port!=8877) e.Cancel=true;
                };
                web.CoreWebView2.Navigate("http://127.0.0.1:8877/");
            } catch(Exception) { MessageBox.Show("UI 预览未能连接。请重新运行 Start-Preview.ps1。",Text); Close(); }
        };
    }
    [STAThread] static void Main() { Application.EnableVisualStyles(); Application.Run(new PreviewWindow()); }
}
