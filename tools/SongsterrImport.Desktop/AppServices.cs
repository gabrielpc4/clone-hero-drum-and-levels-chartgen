// Author: Gabriel Pinheiro de Carvalho
using System.IO;

namespace SongsterrImport.Desktop;

internal static class AppServices
{
    internal static string CookieFilePath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "SongsterrImport",
        "songsterr_cookies.json"
    );

    internal static string LastUrlFilePath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "SongsterrImport",
        "last_songsterr_url.txt"
    );

    internal static string ReadLastUrl()
    {
        if (!File.Exists(LastUrlFilePath))
        {
            return string.Empty;
        }

        return (File.ReadAllText(LastUrlFilePath) ?? string.Empty).Trim();
    }

    internal static void WriteLastUrl(string? url)
    {
        string dir = Path.GetDirectoryName(LastUrlFilePath) ?? string.Empty;
        if (dir.Length == 0)
        {
            return;
        }

        Directory.CreateDirectory(dir);
        string body = (url ?? string.Empty).Replace("\r\n", " ").Replace('\n', ' ').Replace('\r', ' ');
        File.WriteAllText(LastUrlFilePath, body, System.Text.Encoding.UTF8);
    }

    internal static string LastSelectedTrackPathFilePath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "SongsterrImport",
        "last_selected_track_path.txt"
    );

    internal static string ReadLastSelectedTrackPathFromRepository()
    {
        if (!File.Exists(LastSelectedTrackPathFilePath))
        {
            return string.Empty;
        }

        return (File.ReadAllText(LastSelectedTrackPathFilePath) ?? string.Empty).Trim();
    }

    internal static void WriteLastSelectedTrackPathFromRepository(string? pathFromRepositoryRoot)
    {
        string dir = Path.GetDirectoryName(LastSelectedTrackPathFilePath) ?? string.Empty;
        if (dir.Length == 0)
        {
            return;
        }

        Directory.CreateDirectory(dir);
        string line = (pathFromRepositoryRoot ?? string.Empty)
            .Replace("\r", string.Empty)
            .Replace("\n", string.Empty);
        File.WriteAllText(LastSelectedTrackPathFilePath, line, System.Text.Encoding.UTF8);
    }
}
