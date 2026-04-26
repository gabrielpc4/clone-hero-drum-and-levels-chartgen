// Author: Gabriel Pinheiro de Carvalho
using System.IO;
using System.Text.Json;
using System.Windows;
using Microsoft.Web.WebView2.Core;

namespace SongsterrImport.Desktop;

public partial class LoginWindow : Window
{
    public LoginWindow()
    {
        InitializeComponent();
        Loaded += OnWindowLoaded;
    }

    private async void OnWindowLoaded(object sender, RoutedEventArgs e)
    {
        await Browser.EnsureCoreWebView2Async();
        Browser.Source = new Uri("https://www.songsterr.com/", UriKind.Absolute);
    }

    private async void OnSaveCookiesClick(object sender, RoutedEventArgs e)
    {
        if (Browser.CoreWebView2 is null)
        {
            System.Windows.MessageBox.Show("The browser is still starting. Please wait.", "Sign in", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        IReadOnlyList<CoreWebView2Cookie> cookies = await Browser.CoreWebView2.CookieManager
            .GetCookiesAsync("https://www.songsterr.com");
        var items = new List<Dictionary<string, string>>();
        foreach (var c in cookies)
        {
            var d = new Dictionary<string, string>
            {
                ["name"] = c.Name,
                ["value"] = c.Value,
                ["domain"] = c.Domain,
                ["path"] = c.Path,
            };
            items.Add(d);
        }

        string path = AppServices.CookieFilePath;
        string? parent = Path.GetDirectoryName(path);
        if (parent is not null)
        {
            Directory.CreateDirectory(parent);
        }

        var payload = new { cookies = items };
        string json = JsonSerializer.Serialize(
            payload,
            new JsonSerializerOptions { WriteIndented = true }
        );
        try
        {
            await File.WriteAllTextAsync(path, json);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show("Could not save the session: " + ex.Message, "Sign in", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        DialogResult = true;
        Close();
    }
}
