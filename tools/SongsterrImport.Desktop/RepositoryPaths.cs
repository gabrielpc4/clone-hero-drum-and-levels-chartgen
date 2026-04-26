// Author: Gabriel Pinheiro de Carvalho
using System.IO;

namespace SongsterrImport.Desktop;

/// <summary>
/// Resolves and displays file paths against the repository root, including %USERPROFILE% and %LocalAppData% for shorter UI.
/// </summary>
internal static class RepositoryPaths
{
    internal static string ExpandDisplayPath(string? displayText)
    {
        if (string.IsNullOrWhiteSpace(displayText))
        {
            return string.Empty;
        }

        string t = displayText.Trim();
        try
        {
            t = Environment.ExpandEnvironmentVariables(t);
        }
        catch
        {
            // ignore malformed env; Path.GetFullPath will still work for plain paths
        }

        return Path.GetFullPath(t);
    }

    /// <summary>
    /// Treats the input as a path. If it is not rooted, joins with <paramref name="repoRoot"/> (expanded first).
    /// </summary>
    internal static string ResolveToFullPath(string? userPath, string? repoRootDisplay)
    {
        string t = (userPath ?? string.Empty).Trim();
        if (t.Length == 0)
        {
            return string.Empty;
        }

        if (Path.IsPathFullyQualified(t))
        {
            return Path.GetFullPath(t);
        }

        string root = ExpandDisplayPath(repoRootDisplay);
        if (root.Length == 0)
        {
            return Path.GetFullPath(t);
        }

        return Path.GetFullPath(Path.Combine(root, t));
    }

    /// <summary>
    /// If <paramref name="fullPath"/> lies under the expanded repo root, returns a relative path using forward slashes.
    /// </summary>
    internal static string ToPathBelowRepository(string? fullPath, string? repoRootDisplay)
    {
        if (string.IsNullOrEmpty(fullPath))
        {
            return string.Empty;
        }

        string root = ExpandDisplayPath(repoRootDisplay);
        if (root.Length == 0)
        {
            return fullPath;
        }

        return ToPathBelowBase(fullPath, root);
    }

    internal static string ToPathBelowBase(string fullPath, string? baseDirectoryExpanded)
    {
        if (string.IsNullOrEmpty(baseDirectoryExpanded))
        {
            return fullPath;
        }

        string p = Path.GetFullPath(fullPath);
        string b = Path.GetFullPath(baseDirectoryExpanded);
        string rel;
        try
        {
            rel = Path.GetRelativePath(b, p);
        }
        catch
        {
            return ToDisplayWithEnvironmentPrefix(p);
        }

        if (rel.StartsWith("..", StringComparison.Ordinal) || Path.IsPathRooted(rel))
        {
            return ToDisplayWithEnvironmentPrefix(p);
        }

        return rel.Replace(Path.DirectorySeparatorChar, '/');
    }

    /// <summary>
    /// Replaces a leading user profile path with %USERPROFILE% and local app data with %LocalAppData% when possible.
    /// </summary>
    internal static string ToDisplayWithEnvironmentPrefix(string? fullPath)
    {
        if (string.IsNullOrEmpty(fullPath))
        {
            return string.Empty;
        }

        string p = Path.GetFullPath(fullPath);
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (local.Length > 0
            && p.StartsWith(local, StringComparison.OrdinalIgnoreCase)
            && (p.Length == local.Length || p[local.Length] is '\\' or '/'))
        {
            string tail = p[local.Length..].TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            return Path.Combine("%LocalAppData%", tail);
        }

        string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (profile.Length > 0
            && p.StartsWith(profile, StringComparison.OrdinalIgnoreCase)
            && (p.Length == profile.Length || p[profile.Length] is '\\' or '/'))
        {
            string tail2 = p[profile.Length..].TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            return Path.Combine("%USERPROFILE%", tail2);
        }

        return p;
    }
}
