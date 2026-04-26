// Author: Gabriel Pinheiro de Carvalho
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Windows.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;

namespace SongsterrImport.Desktop;

public partial class MainWindow : Window
{
    private const string H_Artist = "Artist";
    private const string H_Title = "Title";
    private const string H_Album = "Album";
    private const string H_Year = "Yr";
    private const string H_Genre = "Genre";
    private const string H_Charter = "Charter";
    private const string H_D = "D";
    private const string H_Dr = "D+";
    private const string H_G = "G";
    private const string H_B = "B";
    private const string H_K = "K";
    private const string H_Bnd = "Bnd";
    private const string H_Rh = "Rh";
    private const string H_GG = "GG";
    private const string H_BG = "BG";
    private const string H_V = "V";
    private const string H_Len = "Duration";
    private const string H_Pr = "Prv";
    private const string H_At = "AT";
    private const string H_Pt = "PT";
    private const string H_Icon = "Icon";
    private const string H_Mod = "Mod";
    private const string H_Cnt = "Cnt";
    private const string H_Load = "Load Phrase";
    private const string H_More = "More";
    private const string H_Processed = "Processed";
    private const string H_End = "End";
    private const string H_5L = "5L";
    private const string H_Pro = "Pro";

    // Defaults (no UI; change here or ask the assistant to adjust).
    private const string DefaultInitialOffsetTicks = "768";
    private const string DefaultFlamAssumptionBeats = "0.0625";
    private const string DefaultReferenceChartPath = "";
    // This machine: `python` on PATH (3.13); `py` not installed.
    private const string DefaultPythonLauncher = "python";

    /// <summary>Repository root path as used for <see cref="RepositoryPaths.ExpandDisplayPath"/>. The executable guesses this at startup; ask the assistant to change the code if your clone lives elsewhere.</summary>
    private string _repositoryRootDisplay = string.Empty;

    private readonly ObservableCollection<SongEntry> _songSource = new();
    private readonly CancellationTokenSource _cts = new();
    private readonly IProgress<string> _log;
    private bool _isBusy;
    private string _pathDownloadedSongsterrMidBelowRepo = string.Empty;
    private string _pathImportOutputSongsterrMidBelowRepo = string.Empty;
    private string _pathSyncSourceFolderBelowRepo = string.Empty;
    private string _syncSongsSubfolderName = string.Empty;
    private string? _songsListSortProperty;
    private ListSortDirection _songsListSortDirection = ListSortDirection.Ascending;

    public MainWindow()
    {
        InitializeComponent();
        _log = new Progress<string>(line =>
        {
            System.Windows.Application.Current?.Dispatcher?.BeginInvoke(
                new Action(
                    () =>
                    {
                        LogText.AppendText(line + Environment.NewLine);
                        LogText.CaretIndex = LogText.Text.Length;
                        LogScroll.ScrollToEnd();
                    }
                )
            );
        });
        string guess = DefaultRepoRootGuess();
        _repositoryRootDisplay = RepositoryPaths.ToDisplayWithEnvironmentPrefix(guess);
        UrlText.Text = AppServices.ReadLastUrl();
        Closing += OnMainWindowClosing;
        UrlText.LostFocus += OnUrlTextLostFocus;
        IncludeSoftNotesCheck.IsChecked = AppServices.ReadIncludeSoftNotesEnabled(defaultValue: true);
        ConvertFlamsToDoubleCheck.IsChecked = AppServices.ReadConvertFlamsToDoubleEnabled(defaultValue: false);
        IncludeSoftNotesCheck.Checked += OnImportOptionsCheckChanged;
        IncludeSoftNotesCheck.Unchecked += OnImportOptionsCheckChanged;
        ConvertFlamsToDoubleCheck.Checked += OnImportOptionsCheckChanged;
        ConvertFlamsToDoubleCheck.Unchecked += OnImportOptionsCheckChanged;
        SongsListView.ItemsSource = _songSource;
        ApplySongFilter();
        UpdateSessionUi();
        LoadSongs();
        UpdateGenerateButtonEnabledState();
    }

    private static string DefaultRepoRootGuess()
    {
        // tools/SongsterrImport.Desktop/bin/Debug/net8.0-windows/ -> 5x .. -> repo root
        string here = AppContext.BaseDirectory;
        var di = new DirectoryInfo(here);
        for (int i = 0; i < 5 && di is not null; i++)
        {
            di = di.Parent;
        }

        if (di is null)
        {
            return here;
        }

        return di.FullName;
    }

    private void OnMainWindowClosing(object? sender, CancelEventArgs e)
    {
        AppServices.WriteLastUrl(UrlText.Text.Trim());
        PersistImportOptions();
        PersistLastSelectedTrack();
    }

    private void OnUrlTextLostFocus(object sender, RoutedEventArgs e)
    {
        AppServices.WriteLastUrl(UrlText.Text.Trim());
    }

    private void OnImportOptionsCheckChanged(object sender, RoutedEventArgs e)
    {
        PersistImportOptions();
    }

    private void PersistImportOptions()
    {
        bool includeSoftNotes = IncludeSoftNotesCheck.IsChecked == true;
        bool convertFlamsToDouble = ConvertFlamsToDoubleCheck.IsChecked == true;
        AppServices.WriteIncludeSoftNotesEnabled(includeSoftNotes);
        AppServices.WriteConvertFlamsToDoubleEnabled(convertFlamsToDouble);
    }

    private void LoadSongs()
    {
        _songSource.Clear();
        string root = RepositoryPaths.ExpandDisplayPath(_repositoryRootDisplay);
        if (string.IsNullOrEmpty(root) || !Directory.Exists(root))
        {
            UpdateSongsStatsText(0, 0);
            UpdateSortColumnHeaderIndicators();
            return;
        }

        string customRoot = Path.Combine(root, "original", "custom");
        if (!Directory.Exists(customRoot))
        {
            UpdateSongsStatsText(0, 0);
            UpdateSortColumnHeaderIndicators();
            return;
        }

        string songsDir = Path.Combine(root, "Songs");
        bool songsDirExists = Directory.Exists(songsDir);
        string repoForDisplay = _repositoryRootDisplay.Trim();

        int completeCount = 0;
        foreach (string directory in Directory.GetDirectories(customRoot).OrderBy(a => a, StringComparer.OrdinalIgnoreCase))
        {
            string name = Path.GetFileName(directory);
            bool inSongs = songsDirExists && Directory.Exists(Path.Combine(songsDir, name));
            if (inSongs)
            {
                completeCount++;
            }

            _songSource.Add(
                SongEntry.FromCustomFolder(
                    directory,
                    name,
                    RepositoryPaths.ToPathBelowRepository(directory, repoForDisplay),
                    inSongs ? "Yes" : "No"
                )
            );
        }

        UpdateSongsStatsText(completeCount, _songSource.Count);
        ApplySongFilter();
        TryRestoreLastSelectedTrackAfterSongsLoad();
    }

    private void PersistLastSelectedTrack()
    {
        if (SongsListView.SelectedItem is SongEntry entry)
        {
            AppServices.WriteLastSelectedTrackPathFromRepository(entry.PathFromRepositoryRoot);
        }
        else
        {
            AppServices.WriteLastSelectedTrackPathFromRepository(string.Empty);
        }
    }

    private void TryRestoreLastSelectedTrackAfterSongsLoad()
    {
        string saved = AppServices.ReadLastSelectedTrackPathFromRepository();
        if (string.IsNullOrEmpty(saved))
        {
            return;
        }

        SongEntry? match = _songSource.FirstOrDefault(
            e => string.Equals(e.PathFromRepositoryRoot, saved, StringComparison.OrdinalIgnoreCase));
        if (match is null)
        {
            return;
        }

        Dispatcher.BeginInvoke(
            new Action(
                () =>
                {
                    SongsListView.SelectedItem = match;
                    SongsListView.UpdateLayout();
                    SongsListView.ScrollIntoView(match);
                    Dispatcher.BeginInvoke(
                        new Action(
                            () =>
                            {
                                if (SongsListView.IsLoaded
                                    && ReferenceEquals(SongsListView.SelectedItem, match)
                                    && _songSource.Contains(match))
                                {
                                    SongsListView.UpdateLayout();
                                    SongsListView.ScrollIntoView(match);
                                }
                            }),
                        DispatcherPriority.ContextIdle);
                }),
            DispatcherPriority.Loaded);
    }

    private void ApplySongFilter()
    {
        if (CollectionViewSource.GetDefaultView(_songSource) is not System.Windows.Data.CollectionView view)
        {
            return;
        }

        string q = (FilterText.Text ?? string.Empty).Trim();
        if (q.Length == 0)
        {
            view.Filter = null;
            ApplyCurrentSongsListSort();
            return;
        }

        view.Filter = o =>
        {
            if (o is not SongEntry s)
            {
                return false;
            }

            return s.BuildSearchableText().Contains(q, StringComparison.OrdinalIgnoreCase);
        };
        ApplyCurrentSongsListSort();
    }

    private void OnFilterTextChanged(object sender, TextChangedEventArgs e)
    {
        ApplySongFilter();
    }

    private void SongsListView_OnSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        try
        {
            if (SongsListView.SelectedItem is not SongEntry entry)
            {
                _pathDownloadedSongsterrMidBelowRepo = string.Empty;
                _pathImportOutputSongsterrMidBelowRepo = string.Empty;
                _pathSyncSourceFolderBelowRepo = string.Empty;
                _syncSongsSubfolderName = string.Empty;
                UpdateGenerateButtonEnabledState();
                return;
            }

            if (string.IsNullOrEmpty(RepositoryPaths.ExpandDisplayPath(_repositoryRootDisplay)))
            {
                UpdateGenerateButtonEnabledState();
                return;
            }

            string name = entry.DisplayName;
            string customDir = entry.FullPath;
            string repoText = _repositoryRootDisplay;
            string downloadFile = Path.Combine(customDir, "songsterr_in.mid");
            string outFile = Path.Combine(customDir, "notes.generated.mid");
            _pathDownloadedSongsterrMidBelowRepo = RepositoryPaths.ToPathBelowRepository(downloadFile, repoText);
            _pathImportOutputSongsterrMidBelowRepo = RepositoryPaths.ToPathBelowRepository(outFile, repoText);
            _pathSyncSourceFolderBelowRepo = RepositoryPaths.ToPathBelowRepository(customDir, repoText);
            _syncSongsSubfolderName = name;
            UpdateGenerateButtonEnabledState();
        }
        finally
        {
            PersistLastSelectedTrack();
        }
    }

    private void SongsListView_OnMouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        SongEntry? entry = GetSongEntryFromListViewEventSource(e) ?? (SongsListView.SelectedItem as SongEntry);
        if (entry is null)
        {
            return;
        }

        if (e.OriginalSource is DependencyObject o && IsUnderGridViewColumnHeader(o))
        {
            return;
        }

        if (!Directory.Exists(entry.FullPath))
        {
            LogText.AppendText("ERROR: folder not found: " + entry.FullPath + Environment.NewLine);
            return;
        }

        OpenFolderInExplorer(entry.FullPath);
    }

    private static void OpenFolderInExplorer(string fullPath)
    {
        var psi = new ProcessStartInfo
        {
            FileName = "explorer.exe",
            UseShellExecute = true,
        };
        psi.ArgumentList.Add(fullPath);
        Process.Start(psi);
    }

    private void OnOpenSyncSourceFolderClick(object sender, RoutedEventArgs e)
    {
        string fullPath = RepositoryPaths.ResolveToFullPath(_pathSyncSourceFolderBelowRepo, RepositoryPathForDisplay);
        if (string.IsNullOrEmpty(fullPath) || !Directory.Exists(fullPath))
        {
            System.Windows.MessageBox.Show("Select a source track in the list first, or the source folder is missing on disk.", "Open source folder", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        OpenFolderInExplorer(fullPath);
    }

    private void OnOpenSongsDestFolderClick(object sender, RoutedEventArgs e)
    {
        string name = _syncSongsSubfolderName.Trim();
        if (name.Length == 0)
        {
            System.Windows.MessageBox.Show("Select a source track in the list first.", "Open dest folder", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        string root = RepositoryPaths.ExpandDisplayPath(_repositoryRootDisplay);
        if (string.IsNullOrEmpty(root) || !Directory.Exists(root))
        {
            System.Windows.MessageBox.Show("The repository root could not be resolved. Ask the assistant to set _repositoryRootDisplay in MainWindow to your Clone Hero project path if autodetection is wrong.", "Open dest folder", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        string fullPath = Path.GetFullPath(Path.Combine(root, "Songs", name));
        if (!Directory.Exists(fullPath))
        {
            System.Windows.MessageBox.Show("The destination folder does not exist yet (it is created when sync succeeds):\n" + fullPath, "Open dest folder", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        OpenFolderInExplorer(fullPath);
    }

    private static bool IsUnderGridViewColumnHeader(DependencyObject start)
    {
        for (DependencyObject? x = start; x is not null; x = VisualTreeHelper.GetParent(x))
        {
            if (x is GridViewColumnHeader)
            {
                return true;
            }
        }

        return false;
    }

    private static SongEntry? GetSongEntryFromListViewEventSource(System.Windows.Input.MouseEventArgs e)
    {
        for (DependencyObject? x = (DependencyObject)e.OriginalSource; x is not null; x = VisualTreeHelper.GetParent(x))
        {
            if (x is System.Windows.Controls.ListViewItem lvi)
            {
                return lvi.DataContext as SongEntry;
            }
        }

        return null;
    }

    private void SongsListView_ColumnHeaderClick(object sender, RoutedEventArgs e)
    {
        if (e.OriginalSource is not GridViewColumnHeader header)
        {
            return;
        }

        if (header.Column is not GridViewColumn col)
        {
            return;
        }

        string? propertyName;
        if (ReferenceEquals(col, SongsColumnProcessed))
        {
            propertyName = nameof(SongEntry.InSongsStatus);
        }
        else
        {
            propertyName = (col.DisplayMemberBinding as System.Windows.Data.Binding)?.Path?.Path;
        }

        if (string.IsNullOrEmpty(propertyName))
        {
            return;
        }

        if (string.Equals(_songsListSortProperty, propertyName, StringComparison.Ordinal))
        {
            _songsListSortDirection = _songsListSortDirection == ListSortDirection.Ascending
                ? ListSortDirection.Descending
                : ListSortDirection.Ascending;
        }
        else
        {
            _songsListSortProperty = propertyName;
            _songsListSortDirection = ListSortDirection.Ascending;
        }

        ApplyCurrentSongsListSort();
    }

    private void UpdateSongsStatsText(int completeCount, int totalCount)
    {
        SongsStatsText.Text = "Complete: " + completeCount + " / " + totalCount;
    }

    private void ResetSongListHeaderBaseTexts()
    {
        SongsHeaderProcessed.Text = H_Processed;
        SongsHeaderTitle.Text = H_Title;
        SongsHeaderArtist.Text = H_Artist;
        SongsHeaderAlbum.Text = H_Album;
        SongsHeaderLen.Text = H_Len;
        SongsHeaderEnd.Text = H_End;
        SongsHeader5L.Text = H_5L;
        SongsHeaderPro.Text = H_Pro;
        SongsHeaderYear.Text = H_Year;
        SongsHeaderGenre.Text = H_Genre;
        SongsHeaderCharter.Text = H_Charter;
        SongsHeaderPr.Text = H_Pr;
        SongsHeaderAt.Text = H_At;
        SongsHeaderPt.Text = H_Pt;
        SongsHeaderIcon.Text = H_Icon;
        SongsHeaderMod.Text = H_Mod;
        SongsHeaderCnt.Text = H_Cnt;
        SongsHeaderLoad.Text = H_Load;
        SongsHeaderMore.Text = H_More;
        SongsHeaderD.Text = H_D;
        SongsHeaderDr.Text = H_Dr;
        SongsHeaderG.Text = H_G;
        SongsHeaderB.Text = H_B;
        SongsHeaderK.Text = H_K;
        SongsHeaderBnd.Text = H_Bnd;
        SongsHeaderRh.Text = H_Rh;
        SongsHeaderGG.Text = H_GG;
        SongsHeaderBG.Text = H_BG;
        SongsHeaderV.Text = H_V;
    }

    private void UpdateSortColumnHeaderIndicators()
    {
        ResetSongListHeaderBaseTexts();
        if (string.IsNullOrEmpty(_songsListSortProperty))
        {
            return;
        }

        string arrow = _songsListSortDirection == ListSortDirection.Ascending ? " \u2191" : " \u2193";
        switch (_songsListSortProperty)
        {
            case nameof(SongEntry.InSongsStatus):
                SongsHeaderProcessed.Text = H_Processed + arrow;
                break;
            case nameof(SongEntry.SongIniTitle):
                SongsHeaderTitle.Text = H_Title + arrow;
                break;
            case nameof(SongEntry.SongIniArtist):
                SongsHeaderArtist.Text = H_Artist + arrow;
                break;
            case nameof(SongEntry.SongIniAlbum):
                SongsHeaderAlbum.Text = H_Album + arrow;
                break;
            case nameof(SongEntry.SongIniLengthDisplay):
                SongsHeaderLen.Text = H_Len + arrow;
                break;
            case nameof(SongEntry.SongIniEndEventsOn):
                SongsHeaderEnd.Text = H_End + arrow;
                break;
            case nameof(SongEntry.SongIniFiveLaneDrumsOn):
                SongsHeader5L.Text = H_5L + arrow;
                break;
            case nameof(SongEntry.SongIniProDrumsOn):
                SongsHeaderPro.Text = H_Pro + arrow;
                break;
            case nameof(SongEntry.SongIniYear):
                SongsHeaderYear.Text = H_Year + arrow;
                break;
            case nameof(SongEntry.SongIniGenre):
                SongsHeaderGenre.Text = H_Genre + arrow;
                break;
            case nameof(SongEntry.SongIniCharter):
                SongsHeaderCharter.Text = H_Charter + arrow;
                break;
            case nameof(SongEntry.SongIniPreviewDisplay):
                SongsHeaderPr.Text = H_Pr + arrow;
                break;
            case nameof(SongEntry.SongIniAlbumTrack):
                SongsHeaderAt.Text = H_At + arrow;
                break;
            case nameof(SongEntry.SongIniPlaylistTrack):
                SongsHeaderPt.Text = H_Pt + arrow;
                break;
            case nameof(SongEntry.SongIniIcon):
                SongsHeaderIcon.Text = H_Icon + arrow;
                break;
            case nameof(SongEntry.SongIniModchart):
                SongsHeaderMod.Text = H_Mod + arrow;
                break;
            case nameof(SongEntry.SongIniCount):
                SongsHeaderCnt.Text = H_Cnt + arrow;
                break;
            case nameof(SongEntry.SongIniLoadingShort):
                SongsHeaderLoad.Text = H_Load + arrow;
                break;
            case nameof(SongEntry.SongIniMore):
                SongsHeaderMore.Text = H_More + arrow;
                break;
            case nameof(SongEntry.SongIniDiffDrums):
                SongsHeaderD.Text = H_D + arrow;
                break;
            case nameof(SongEntry.SongIniDiffDrumsReal):
                SongsHeaderDr.Text = H_Dr + arrow;
                break;
            case nameof(SongEntry.SongIniDiffGuitar):
                SongsHeaderG.Text = H_G + arrow;
                break;
            case nameof(SongEntry.SongIniDiffBass):
                SongsHeaderB.Text = H_B + arrow;
                break;
            case nameof(SongEntry.SongIniDiffKeys):
                SongsHeaderK.Text = H_K + arrow;
                break;
            case nameof(SongEntry.SongIniDiffBand):
                SongsHeaderBnd.Text = H_Bnd + arrow;
                break;
            case nameof(SongEntry.SongIniDiffRhythm):
                SongsHeaderRh.Text = H_Rh + arrow;
                break;
            case nameof(SongEntry.SongIniDiffGuitarGhl):
                SongsHeaderGG.Text = H_GG + arrow;
                break;
            case nameof(SongEntry.SongIniDiffBassGhl):
                SongsHeaderBG.Text = H_BG + arrow;
                break;
            case nameof(SongEntry.SongIniDiffVocals):
                SongsHeaderV.Text = H_V + arrow;
                break;
        }
    }

    private void ApplyCurrentSongsListSort()
    {
        if (string.IsNullOrEmpty(_songsListSortProperty))
        {
            UpdateSortColumnHeaderIndicators();
            return;
        }

        if (CollectionViewSource.GetDefaultView(_songSource) is not System.Windows.Data.CollectionView view)
        {
            return;
        }

        view.SortDescriptions.Clear();
        view.SortDescriptions.Add(new SortDescription(_songsListSortProperty, _songsListSortDirection));
        UpdateSortColumnHeaderIndicators();
    }

    private void UpdateSessionUi()
    {
        string cookieFilePath = AppServices.CookieFilePath;
        bool hasSession = File.Exists(cookieFilePath);
        if (hasSession)
        {
            SessionStatusText.Text = "Logged in";
            SessionActionButton.Content = "Logout";
        }
        else
        {
            SessionStatusText.Text = "Not signed in";
            SessionActionButton.Content = "Login";
        }
    }

    private void OnSessionActionClick(object sender, RoutedEventArgs e)
    {
        string cookieFilePath = AppServices.CookieFilePath;
        if (File.Exists(cookieFilePath))
        {
            try
            {
                File.Delete(cookieFilePath);
            }
            catch (Exception ex)
            {
                System.Windows.MessageBox.Show("Could not remove the saved session: " + ex.Message, "Logout", MessageBoxButton.OK, MessageBoxImage.Error);
                return;
            }

            UpdateSessionUi();
        }

        var w = new LoginWindow { Owner = this };
        bool? result = w.ShowDialog();
        if (result is true)
        {
            UpdateSessionUi();
        }
    }

    private IProgress<string> LogProgress => _log;

    private void UpdateGenerateButtonEnabledState()
    {
        if (_isBusy)
        {
            GenerateDrumChartButton.IsEnabled = false;
            return;
        }

        string resolvedMid = RepositoryPaths.ResolveToFullPath(_pathDownloadedSongsterrMidBelowRepo, RepositoryPathForDisplay);
        bool hasSongsterrMidi = resolvedMid.Length > 0 && File.Exists(resolvedMid);
        GenerateDrumChartButton.IsEnabled = hasSongsterrMidi;
    }

    private void SetBusy(bool active)
    {
        _isBusy = active;
        DownloadButton.IsEnabled = !active;
        UpdateGenerateButtonEnabledState();
    }

    private void OnDownloadClick(object sender, RoutedEventArgs e)
    {
        _ = RunDownloadOnlyAsync();
    }

    private void OnGenerateDrumChartClick(object sender, RoutedEventArgs e)
    {
        _ = RunGenerateDrumChartAsync();
    }

    private string RepoRoot => RepositoryPaths.ExpandDisplayPath(_repositoryRootDisplay);
    private string Py => DefaultPythonLauncher;
    private string CookiePath => AppServices.CookieFilePath;

    private string RepositoryPathForDisplay => _repositoryRootDisplay;

    private string DownloadScript => Path.Combine(RepoRoot, "src", "songsterr_parsing", "download_songsterr_midi.py");
    private string ImportScript => Path.Combine(RepoRoot, "src", "songsterr_parsing", "import_songsterr.py");
    private string SyncScript => Path.Combine(RepoRoot, "copy_song_to_clone_hero.ps1");

    private IReadOnlyDictionary<string, string> BuildPythonEnv() =>
        new Dictionary<string, string> { { "PYTHONPATH", Path.Combine(RepoRoot, "src") + ";" + Path.Combine(RepoRoot, "src", "chart_generation") } };

    private string RepoPathForResolve => _repositoryRootDisplay;

    private async Task RunDownloadOnlyAsync()
    {
        if (_isBusy)
        {
            return;
        }

        SetBusy(true);
        try
        {
            int code = await DoDownloadAsync();
            if (code >= 0)
            {
                LogProgress.Report(code == 0 ? ">> Download finished successfully" : ">> Download exit code: " + code);
            }
        }
        catch (Exception ex)
        {
            LogProgress.Report("ERROR: " + ex);
        }
        finally
        {
            SetBusy(false);
        }
    }

    /// <returns>Process exit code, or -1 if validation failed (user was already notified).</returns>
    private async Task<int> DoDownloadAsync()
    {
        if (!File.Exists(CookiePath))
        {
            string cookieSh = RepositoryPaths.ToDisplayWithEnvironmentPrefix(CookiePath);
            System.Windows.MessageBox.Show("Sign in and save the session first. Missing cookie file: " + cookieSh, "Download", MessageBoxButton.OK, MessageBoxImage.Warning);
            return -1;
        }

        if (!File.Exists(DownloadScript))
        {
            string scriptDisplay = RepositoryPaths.ToPathBelowRepository(DownloadScript, RepoPathForResolve);
            System.Windows.MessageBox.Show("Script not found: " + scriptDisplay, "Download", MessageBoxButton.OK, MessageBoxImage.Error);
            return -1;
        }

        string url = UrlText.Text.Trim();
        AppServices.WriteLastUrl(url);
        string outMid = RepositoryPaths.ResolveToFullPath(_pathDownloadedSongsterrMidBelowRepo, RepoPathForResolve);
        if (url.Length == 0 || outMid.Length == 0)
        {
            System.Windows.MessageBox.Show("Fill in the URL and select a source track (paths for the downloaded MIDI are set from the selection).", "Download", MessageBoxButton.OK, MessageBoxImage.Information);
            return -1;
        }

        string? parent = Path.GetDirectoryName(outMid);
        if (parent is not null)
        {
            Directory.CreateDirectory(parent);
        }

        var argList = new List<string> { DownloadScript, url, outMid, "--cookie-file", CookiePath };
        return await ProcessRunner.RunWithLogAsync(Py, argList, RepoRoot, BuildPythonEnv(), LogProgress, _cts.Token);
    }

    /// <returns>Process exit code, or -1 if validation failed (user was already notified).</returns>
    private async Task<int> DoImportAsync()
    {
        if (!File.Exists(ImportScript))
        {
            string scriptDisplay = RepositoryPaths.ToPathBelowRepository(ImportScript, RepoPathForResolve);
            System.Windows.MessageBox.Show("Script not found: " + scriptDisplay, "Import", MessageBoxButton.OK, MessageBoxImage.Error);
            return -1;
        }

        string inputMid = RepositoryPaths.ResolveToFullPath(_pathDownloadedSongsterrMidBelowRepo, RepoPathForResolve);
        string outMid = RepositoryPaths.ResolveToFullPath(_pathImportOutputSongsterrMidBelowRepo, RepoPathForResolve);
        if (inputMid.Length == 0 || outMid.Length == 0)
        {
            System.Windows.MessageBox.Show("Select a source track in the list so the import paths are set.", "Import", MessageBoxButton.OK, MessageBoxImage.Information);
            return -1;
        }

        string? parent = Path.GetDirectoryName(outMid);
        if (parent is not null)
        {
            Directory.CreateDirectory(parent);
        }

        if (!File.Exists(inputMid))
        {
            string msgPath = RepositoryPaths.ToPathBelowRepository(inputMid, RepoPathForResolve);
            System.Windows.MessageBox.Show("No input MIDI file yet: " + msgPath, "Import", MessageBoxButton.OK, MessageBoxImage.Information);
            return -1;
        }

        var list = new List<string> { ImportScript, inputMid, outMid, "--initial-offset-ticks", DefaultInitialOffsetTicks };
        string flamBeats = DefaultFlamAssumptionBeats.Replace(',', '.').Trim();
        list.AddRange(new[] { "--dedup-beats", flamBeats });
        if (IncludeSoftNotesCheck.IsChecked != true)
        {
            list.Add("--filter-weak-snares");
        }

        if (ConvertFlamsToDoubleCheck.IsChecked != true)
        {
            list.Add("--no-convert-flams");
        }

        string reff = DefaultReferenceChartPath.Trim();
        if (reff.Length > 0)
        {
            list.AddRange(new[] { "--ref-path", RepositoryPaths.ResolveToFullPath(reff, RepoPathForResolve) });
        }

        return await ProcessRunner.RunWithLogAsync(Py, list, RepoRoot, BuildPythonEnv(), LogProgress, _cts.Token);
    }

    /// <returns>Process exit code, or -1 if validation failed (user was already notified).</returns>
    private async Task<int> DoSyncAsync()
    {
        if (!File.Exists(SyncScript))
        {
            string scriptDisplay = RepositoryPaths.ToPathBelowRepository(SyncScript, RepoPathForResolve);
            System.Windows.MessageBox.Show("Script not found: " + scriptDisplay, "Sync", MessageBoxButton.OK, MessageBoxImage.Error);
            return -1;
        }

        string sub = _syncSongsSubfolderName.Trim();
        string source = RepositoryPaths.ResolveToFullPath(_pathSyncSourceFolderBelowRepo, RepoPathForResolve);
        if (sub.Length == 0 || source.Length == 0)
        {
            System.Windows.MessageBox.Show("Select a source track in the list so the sync source and destination name are set.", "Sync", MessageBoxButton.OK, MessageBoxImage.Information);
            return -1;
        }

        string powerShell = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.System),
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe"
        );
        if (!File.Exists(powerShell))
        {
            powerShell = "powershell";
        }

        var list = new List<string>
        {
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SyncScript,
            "-SourcePath", source,
            "-SongsSubPath", sub
        };
        return await ProcessRunner.RunWithLogAsync(
            powerShell,
            list,
            Path.GetDirectoryName(SyncScript) ?? RepoRoot,
            null,
            LogProgress,
            _cts.Token
        );
    }

    private async Task RunGenerateDrumChartAsync()
    {
        if (_isBusy)
        {
            return;
        }

        string songsterrMid = RepositoryPaths.ResolveToFullPath(_pathDownloadedSongsterrMidBelowRepo, RepoPathForResolve);
        if (string.IsNullOrEmpty(songsterrMid) || !File.Exists(songsterrMid))
        {
            System.Windows.MessageBox.Show("Download the Songsterr MIDI for the selected track first (songsterr_in.mid).", "Generate Drum Chart", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        SetBusy(true);
        try
        {
            int code = await DoImportAsync();
            if (code < 0)
            {
                return;
            }

            if (code != 0)
            {
                LogProgress.Report(">> Generate Drum Chart stopped: import failed (exit " + code + ").");
                return;
            }

            code = await DoSyncAsync();
            if (code < 0)
            {
                return;
            }

            if (code == 0)
            {
                LogProgress.Report(">> Generate Drum Chart completed successfully.");
                LoadSongs();
            }
            else
            {
                LogProgress.Report(">> Generate Drum Chart stopped: sync failed (exit " + code + ").");
            }
        }
        catch (Exception ex)
        {
            LogProgress.Report("ERROR: " + ex);
        }
        finally
        {
            SetBusy(false);
        }
    }

    protected override void OnClosing(CancelEventArgs e)
    {
        _cts.Cancel();
        _cts.Dispose();
        base.OnClosing(e);
    }
}
