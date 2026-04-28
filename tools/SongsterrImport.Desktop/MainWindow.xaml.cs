// Author: Gabriel Pinheiro de Carvalho
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;
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
    private const string H_NotesMidModified = "Drums Generated At";
    private const string H_DifficultiesGenerated = "Difficulties Generated at";
    private const string H_ChartLevels = "Difficulties in Orig Chart";
    private const string H_End = "End";
    private const string H_5L = "5L";
    private const string H_Pro = "Pro";

    // Defaults (no UI; change here or ask the assistant to adjust).
    private const string DefaultInitialOffsetTicks = "768";
    private const string DefaultReferenceChartPath = "";
    private static readonly Regex SongsterrManualMidiPattern = new(
        @"^.*(?<month>\d{2})-(?<day>\d{2})-(?<year>\d{4})\.mid$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant
    );
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
        Closing += OnMainWindowClosing;
        ExpertCymbalAlternationWholeCheck.IsChecked = AppServices.ReadExpertCymbalAlternationWholeEnabled(defaultValue: false);
        ThinAllCymbalLinesCheck.IsChecked = AppServices.ReadThinAllCymbalLinesEnabled(defaultValue: false);
        ExpertCymbalAlternationWholeCheck.Checked += OnImportOptionsCheckChanged;
        ExpertCymbalAlternationWholeCheck.Unchecked += OnImportOptionsCheckChanged;
        ThinAllCymbalLinesCheck.Checked += OnImportOptionsCheckChanged;
        ThinAllCymbalLinesCheck.Unchecked += OnImportOptionsCheckChanged;
        SongsListView.ItemsSource = _songSource;
        ApplySongFilter();
        LoadSongs();
        UpdateGenerateButtonEnabledState();
    }

    private static string DefaultRepoRootGuess()
    {
        // tools/SongsterrImport.Desktop/bin/Debug/net8.0-windows10.0.19041.0/ -> 5x .. -> repo root
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
        PersistImportOptions();
        PersistLastSelectedTrack();
    }

    private void OnImportOptionsCheckChanged(object sender, RoutedEventArgs e)
    {
        PersistImportOptions();
    }

    private void PersistImportOptions()
    {
        bool expertCymbalAlt = ExpertCymbalAlternationWholeCheck.IsChecked == true;
        bool thinAllCymbals = ThinAllCymbalLinesCheck.IsChecked == true;
        AppServices.WriteExpertCymbalAlternationWholeEnabled(expertCymbalAlt);
        AppServices.WriteThinAllCymbalLinesEnabled(thinAllCymbals);
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
            string songsFolderPath = Path.Combine(songsDir, name);
            bool inSongs = songsDirExists && Directory.Exists(songsFolderPath);
            if (inSongs)
            {
                completeCount++;
            }

            _songSource.Add(
                SongEntry.FromCustomFolder(
                    directory,
                    name,
                    RepositoryPaths.ToPathBelowRepository(directory, repoForDisplay),
                    inSongs ? "Yes" : "No",
                    inSongs ? songsFolderPath : null
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
            string outFile = Path.Combine(customDir, "notes.generated.mid");
            _pathDownloadedSongsterrMidBelowRepo = string.Empty;
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
        else if (ReferenceEquals(col, SongsColumnChartLevels))
        {
            propertyName = nameof(SongEntry.ChartAuthoredLevelsSortKey);
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
        SongsHeaderNotesMidModified.Text = H_NotesMidModified;
        SongsHeaderDifficultiesGenerated.Text = H_DifficultiesGenerated;
        SongsHeaderChartLevels.Text = H_ChartLevels;
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
            case nameof(SongEntry.NotesMidModifiedDisplay):
                SongsHeaderNotesMidModified.Text = H_NotesMidModified + arrow;
                break;
            case nameof(SongEntry.DifficultiesGeneratedDisplay):
                SongsHeaderDifficultiesGenerated.Text = H_DifficultiesGenerated + arrow;
                break;
            case nameof(SongEntry.ChartAuthoredLevelsSortKey):
                SongsHeaderChartLevels.Text = H_ChartLevels + arrow;
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

    private IProgress<string> LogProgress => _log;

    private void UpdateGenerateButtonEnabledState()
    {
        if (_isBusy)
        {
            GenerateDrumChartButton.IsEnabled = false;
            GenerateDifficultiesButton.IsEnabled = false;
            GenerateVocalsButton.IsEnabled = false;
            GenerateAllDifficultiesInSongsButton.IsEnabled = false;
            return;
        }

        GenerateDrumChartButton.IsEnabled = true;
        GenerateDifficultiesButton.IsEnabled = true;
        GenerateVocalsButton.IsEnabled = true;
        GenerateAllDifficultiesInSongsButton.IsEnabled = true;
    }

    private void SetBusy(bool active)
    {
        _isBusy = active;
        UpdateGenerateButtonEnabledState();
    }

    private void OnGenerateDrumChartClick(object sender, RoutedEventArgs e)
    {
        _ = RunGenerateDrumChartAsync();
    }

    private void OnGenerateDifficultiesClick(object sender, RoutedEventArgs e)
    {
        _ = RunGenerateDifficultiesAsync();
    }

    private void OnGenerateVocalsClick(object sender, RoutedEventArgs e)
    {
        _ = RunGenerateVocalsAsync();
    }

    private void OnGenerateAllDifficultiesInSongsClick(object sender, RoutedEventArgs e)
    {
        _ = RunGenerateAllDifficultiesInSongsAsync();
    }

    private void OnOpenCymbalToolClick(object sender, RoutedEventArgs e)
    {
        var toolWindow = new CymbalAlternationWindow
        {
            Owner = this
        };
        toolWindow.ShowDialog();
    }

    private string RepoRoot => RepositoryPaths.ExpandDisplayPath(_repositoryRootDisplay);
    private string Py => DefaultPythonLauncher;

    private string RepositoryPathForDisplay => _repositoryRootDisplay;

    private string ImportScript => Path.Combine(RepoRoot, "src", "songsterr_parsing", "import_songsterr.py");
    private string SyncScript => Path.Combine(RepoRoot, "copy_song_to_clone_hero.ps1");
    private string GenerateDifficultiesScript => Path.Combine(RepoRoot, "tools", "generate_difficulties_midi.py");
    private string GenerateVocalsScript => Path.Combine(RepoRoot, "tools", "generate_vocals_midi.py");

    private IReadOnlyDictionary<string, string> BuildPythonEnv() =>
        new Dictionary<string, string>
        {
            {
                "PYTHONPATH",
                string.Join(";", new[]
                {
                    Path.Combine(RepoRoot, "src"),
                    Path.Combine(RepoRoot, "src", "chart_generation"),
                    Path.Combine(RepoRoot, "src", "difficulty_generation")
                })
            }
        };

    private string RepoPathForResolve => _repositoryRootDisplay;

    /// <returns>Process exit code, or -1 if validation failed (user was already notified).</returns>
    private async Task<int> DoImportAsync()
    {
        if (!File.Exists(ImportScript))
        {
            string scriptDisplay = RepositoryPaths.ToPathBelowRepository(ImportScript, RepoPathForResolve);
            System.Windows.MessageBox.Show("Script not found: " + scriptDisplay, "Import", MessageBoxButton.OK, MessageBoxImage.Error);
            return -1;
        }

        string inputMid = ResolveDetectedSongsterrInputMidiPath();
        string outMid = RepositoryPaths.ResolveToFullPath(_pathImportOutputSongsterrMidBelowRepo, RepoPathForResolve);
        if (inputMid.Length == 0 || outMid.Length == 0)
        {
            System.Windows.MessageBox.Show(
                "Selecione uma musica e garanta que existe um MIDI do Songsterr na pasta de origem terminando com MM-DD-YYYY.mid.",
                "Import",
                MessageBoxButton.OK,
                MessageBoxImage.Information
            );
            return -1;
        }

        string? parent = Path.GetDirectoryName(outMid);
        if (parent is not null)
        {
            Directory.CreateDirectory(parent);
        }

        var list = new List<string> { ImportScript, inputMid, outMid, "--initial-offset-ticks", DefaultInitialOffsetTicks };

        if (ExpertCymbalAlternationWholeCheck.IsChecked == true)
        {
            list.Add("--expert-cymbal-alternation-whole");
            if (ThinAllCymbalLinesCheck.IsChecked == true)
            {
                list.Add("--thin-all-cymbal-lines");
            }
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

        string songsterrMid = ResolveDetectedSongsterrInputMidiPath();
        if (string.IsNullOrEmpty(songsterrMid))
        {
            string sourceFolderPath = RepositoryPaths.ResolveToFullPath(_pathSyncSourceFolderBelowRepo, RepoPathForResolve);
            string folderText = sourceFolderPath.Length == 0
                ? "(nenhuma pasta selecionada)"
                : RepositoryPaths.ToPathBelowRepository(sourceFolderPath, RepoPathForResolve);

            System.Windows.MessageBox.Show(
                "Nao encontrei MIDI manual do Songsterr na pasta da musica.\n\n"
                + "Padrao esperado: terminar com MM-DD-YYYY.mid\n"
                + "Exemplos:\n"
                + "- Pictures-12-21-2025.mid\n"
                + "- System of a Down-Radio_Video-04-24-2026.mid\n\n"
                + "Pasta atual: " + folderText,
                "Generate Drum Chart",
                MessageBoxButton.OK,
                MessageBoxImage.Information
            );
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
                WriteDrumChartSidecar(_syncSongsSubfolderName.Trim());
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

    private async Task RunGenerateDifficultiesAsync()
    {
        if (_isBusy)
        {
            return;
        }

        if (!File.Exists(GenerateDifficultiesScript))
        {
            string scriptDisplay = RepositoryPaths.ToPathBelowRepository(GenerateDifficultiesScript, RepoPathForResolve);
            System.Windows.MessageBox.Show("Script not found: " + scriptDisplay, "Generate Difficulties", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        if (string.IsNullOrWhiteSpace(_syncSongsSubfolderName))
        {
            System.Windows.MessageBox.Show(
                "Select a track in the list so the target folder under Songs/ is known.",
                "Generate Difficulties",
                MessageBoxButton.OK,
                MessageBoxImage.Information
            );
            return;
        }

        string? notesFullPath = TryResolveSongsDestNotesMidFullPath();
        if (string.IsNullOrEmpty(notesFullPath) || !File.Exists(notesFullPath))
        {
            string display = notesFullPath is { Length: > 0 } p
                ? p
                : Path.Combine(RepoRoot, "Songs", _syncSongsSubfolderName.Trim(), "notes.mid");
            System.Windows.MessageBox.Show(
                "Could not find notes.mid in the Clone Hero song folder. Run import + sync first, or add the file yourself.\n\n"
                + "Expected path:\n" + display,
                "Generate Difficulties",
                MessageBoxButton.OK,
                MessageBoxImage.Information
            );
            return;
        }

        SetBusy(true);
        try
        {
            var args = new List<string> { GenerateDifficultiesScript, notesFullPath };
            int code = await ProcessRunner.RunWithLogAsync(
                Py,
                args,
                RepoRoot,
                BuildPythonEnv(),
                LogProgress,
                _cts.Token
            );
            if (code == 0)
            {
                WriteDifficultiesSidecar(_syncSongsSubfolderName.Trim());
                LogProgress.Report(">> Generate Difficulties completed successfully.");
                LoadSongs();
            }
            else
            {
                LogProgress.Report(">> Generate Difficulties failed (exit " + code + ").");
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

    private async Task RunGenerateVocalsAsync()
    {
        if (_isBusy)
        {
            return;
        }

        if (!File.Exists(GenerateVocalsScript))
        {
            string scriptDisplay = RepositoryPaths.ToPathBelowRepository(GenerateVocalsScript, RepoPathForResolve);
            System.Windows.MessageBox.Show("Script not found: " + scriptDisplay, "Generate Vocals", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        string sourceMidiPath = ResolveDetectedSongsterrInputMidiPath();
        if (string.IsNullOrEmpty(sourceMidiPath))
        {
            string sourceFolderPath = RepositoryPaths.ResolveToFullPath(_pathSyncSourceFolderBelowRepo, RepoPathForResolve);
            string folderText = sourceFolderPath.Length == 0
                ? "(nenhuma pasta selecionada)"
                : RepositoryPaths.ToPathBelowRepository(sourceFolderPath, RepoPathForResolve);

            System.Windows.MessageBox.Show(
                "Nao encontrei MIDI manual com track vocal na pasta da musica.\n\n"
                + "Padrao esperado: terminar com MM-DD-YYYY.mid\n\n"
                + "Pasta atual: " + folderText,
                "Generate Vocals",
                MessageBoxButton.OK,
                MessageBoxImage.Information
            );
            return;
        }

        string? notesFullPath = TryResolveSongsDestNotesMidFullPath();
        if (string.IsNullOrEmpty(notesFullPath) || !File.Exists(notesFullPath))
        {
            string display = notesFullPath is { Length: > 0 } pathValue
                ? pathValue
                : Path.Combine(RepoRoot, "Songs", _syncSongsSubfolderName.Trim(), "notes.mid");
            System.Windows.MessageBox.Show(
                "Could not find notes.mid in the Clone Hero song folder. Run import + sync first, or add the file yourself.\n\n"
                + "Expected path:\n" + display,
                "Generate Vocals",
                MessageBoxButton.OK,
                MessageBoxImage.Information
            );
            return;
        }

        string customSongDir = RepositoryPaths.ResolveToFullPath(_pathSyncSourceFolderBelowRepo, RepoPathForResolve);
        if (string.IsNullOrWhiteSpace(customSongDir) || !Directory.Exists(customSongDir))
        {
            System.Windows.MessageBox.Show(
                "Select a track in the list so the custom song folder can be resolved.",
                "Generate Vocals",
                MessageBoxButton.OK,
                MessageBoxImage.Information
            );
            return;
        }

        SetBusy(true);
        try
        {
            var args = new List<string>
            {
                GenerateVocalsScript,
                notesFullPath,
                sourceMidiPath,
                "--custom-song-dir",
                customSongDir,
            };
            int code = await ProcessRunner.RunWithLogAsync(
                Py,
                args,
                RepoRoot,
                BuildPythonEnv(),
                LogProgress,
                _cts.Token
            );
            if (code == 0)
            {
                LogProgress.Report(">> Generate Vocals completed successfully.");
                LoadSongs();
            }
            else
            {
                LogProgress.Report(">> Generate Vocals failed (exit " + code + ").");
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

    private string? TryResolveSongsDestNotesMidFullPath()
    {
        if (string.IsNullOrWhiteSpace(_syncSongsSubfolderName))
        {
            return null;
        }

        string fullPath = Path.GetFullPath(
            Path.Combine(RepoRoot, "Songs", _syncSongsSubfolderName.Trim(), "notes.mid")
        );
        return fullPath;
    }

    private async Task RunGenerateAllDifficultiesInSongsAsync()
    {
        if (_isBusy)
        {
            return;
        }

        if (!File.Exists(GenerateDifficultiesScript))
        {
            string scriptDisplay = RepositoryPaths.ToPathBelowRepository(GenerateDifficultiesScript, RepoPathForResolve);
            System.Windows.MessageBox.Show("Script not found: " + scriptDisplay, "Generate all difficulties", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        string songsDir = Path.GetFullPath(Path.Combine(RepoRoot, "Songs"));
        if (!Directory.Exists(songsDir))
        {
            System.Windows.MessageBox.Show("Songs folder not found:\n" + songsDir, "Generate all difficulties", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        bool confirmed = System.Windows.MessageBox.Show(
            "This will run difficulty generation for every subfolder in Songs/ that has notes.mid, " +
            "skipping Harmonix (official) charts. Each file gets a backup before overwrite.\n\n" +
            "Songs root:\n" + songsDir + "\n\nContinue?",
            "Generate all difficulties (Songs/)",
            MessageBoxButton.OKCancel,
            MessageBoxImage.Question
        ) == MessageBoxResult.OK;
        if (!confirmed)
        {
            return;
        }

        SetBusy(true);
        try
        {
            var args = new List<string> { GenerateDifficultiesScript, "--scan-songs" };
            int code = await ProcessRunner.RunWithLogAsync(
                Py,
                args,
                RepoRoot,
                BuildPythonEnv(),
                LogProgress,
                _cts.Token
            );
            if (code == 0)
            {
                WriteAllDifficultiesSidecars(songsDir);
                LogProgress.Report(">> Generate all difficulties (Songs/) completed successfully.");
                LoadSongs();
            }
            else
            {
                LogProgress.Report(">> Generate all difficulties (Songs/) finished with errors (exit " + code + ").");
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

    private void WriteDrumChartSidecar(string subfolderName)
    {
        if (string.IsNullOrWhiteSpace(subfolderName))
        {
            return;
        }

        string sidecar = Path.Combine(RepoRoot, "Songs", subfolderName, ".drum_chart_ts");
        try
        {
            File.WriteAllText(sidecar, DateTime.Now.ToString("yyyy-MM-dd HH:mm", System.Globalization.CultureInfo.InvariantCulture), System.Text.Encoding.UTF8);
        }
        catch
        {
            // non-critical
        }
    }

    private void WriteDifficultiesSidecar(string subfolderName)
    {
        if (string.IsNullOrWhiteSpace(subfolderName))
        {
            return;
        }

        string sidecar = Path.Combine(RepoRoot, "Songs", subfolderName, ".difficulties_ts");
        try
        {
            File.WriteAllText(sidecar, DateTime.Now.ToString("yyyy-MM-dd HH:mm", System.Globalization.CultureInfo.InvariantCulture), System.Text.Encoding.UTF8);
        }
        catch
        {
            // non-critical
        }
    }

    private void WriteAllDifficultiesSidecars(string songsDir)
    {
        if (!Directory.Exists(songsDir))
        {
            return;
        }

        string ts = DateTime.Now.ToString("yyyy-MM-dd HH:mm", System.Globalization.CultureInfo.InvariantCulture);
        foreach (string subdir in Directory.GetDirectories(songsDir))
        {
            if (!File.Exists(Path.Combine(subdir, "notes.mid")))
            {
                continue;
            }

            try
            {
                File.WriteAllText(Path.Combine(subdir, ".difficulties_ts"), ts, System.Text.Encoding.UTF8);
            }
            catch
            {
                // non-critical
            }
        }
    }

    protected override void OnClosing(CancelEventArgs e)
    {
        _cts.Cancel();
        _cts.Dispose();
        base.OnClosing(e);
    }

    private string ResolveDetectedSongsterrInputMidiPath()
    {
        string sourceFolderPath = RepositoryPaths.ResolveToFullPath(_pathSyncSourceFolderBelowRepo, RepoPathForResolve);
        if (sourceFolderPath.Length == 0 || !Directory.Exists(sourceFolderPath))
        {
            _pathDownloadedSongsterrMidBelowRepo = string.Empty;
            return string.Empty;
        }

        string detectedMidiPath = FindLatestSongsterrManualMidiPath(sourceFolderPath);
        if (detectedMidiPath.Length == 0)
        {
            _pathDownloadedSongsterrMidBelowRepo = string.Empty;
            return string.Empty;
        }

        _pathDownloadedSongsterrMidBelowRepo = RepositoryPaths.ToPathBelowRepository(detectedMidiPath, RepoPathForResolve);
        return detectedMidiPath;
    }

    private static string FindLatestSongsterrManualMidiPath(string sourceFolderPath)
    {
        if (!Directory.Exists(sourceFolderPath))
        {
            return string.Empty;
        }

        string selectedMidiPath = string.Empty;
        DateTime selectedRevisionDate = DateTime.MinValue;
        DateTime selectedWriteTimeUtc = DateTime.MinValue;
        string selectedFileName = string.Empty;

        foreach (string filePath in Directory.EnumerateFiles(sourceFolderPath, "*.mid", SearchOption.TopDirectoryOnly))
        {
            string fileName = Path.GetFileName(filePath);
            if (!TryParseSongsterrRevisionDate(fileName, out DateTime revisionDate))
            {
                continue;
            }

            DateTime writeTimeUtc = File.GetLastWriteTimeUtc(filePath);
            bool shouldReplaceSelection = false;
            if (revisionDate > selectedRevisionDate)
            {
                shouldReplaceSelection = true;
            }
            else if (revisionDate == selectedRevisionDate)
            {
                if (writeTimeUtc > selectedWriteTimeUtc)
                {
                    shouldReplaceSelection = true;
                }
                else if (writeTimeUtc == selectedWriteTimeUtc)
                {
                    if (string.Compare(fileName, selectedFileName, StringComparison.OrdinalIgnoreCase) > 0)
                    {
                        shouldReplaceSelection = true;
                    }
                }
            }

            if (shouldReplaceSelection)
            {
                selectedMidiPath = filePath;
                selectedRevisionDate = revisionDate;
                selectedWriteTimeUtc = writeTimeUtc;
                selectedFileName = fileName;
            }
        }

        return selectedMidiPath;
    }

    private static bool TryParseSongsterrRevisionDate(string fileName, out DateTime revisionDate)
    {
        revisionDate = DateTime.MinValue;
        if (string.IsNullOrWhiteSpace(fileName))
        {
            return false;
        }

        Match match = SongsterrManualMidiPattern.Match(fileName);
        if (!match.Success)
        {
            return false;
        }

        string month = match.Groups["month"].Value;
        string day = match.Groups["day"].Value;
        string year = match.Groups["year"].Value;
        string dateText = year + "-" + month + "-" + day;
        return DateTime.TryParseExact(
            dateText,
            "yyyy-MM-dd",
            CultureInfo.InvariantCulture,
            DateTimeStyles.None,
            out revisionDate
        );
    }
}
