// Author: Gabriel Pinheiro de Carvalho
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Drawing;
using System.Globalization;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using Microsoft.Win32;

namespace SongsterrImport.Desktop;

public partial class CymbalAlternationWindow : Window
{
    private readonly ObservableCollection<TickIntervalItem> _intervalItems = new();
    private readonly CymbalRegionPreviewControl _regionPreview;

    private bool _isLoadingState;
    private nint _cymbalToolWindowHandle;
    private bool _nextOcrFillsStart = true;

    public CymbalAlternationWindow()
    {
        InitializeComponent();
        StartTickTextBox.Text = "0";
        EndTickTextBox.Text = "0";
        IntervalsListBox.ItemsSource = _intervalItems;
        StartTickTextBox.LostFocus += (_, __) => TrySaveState();
        EndTickTextBox.LostFocus += (_, __) => TrySaveState();
        MidiPathTextBox.LostFocus += (_, __) => TrySaveState();

        _regionPreview = new CymbalRegionPreviewControl
        {
            OcrClientRegion = new Rectangle(0, 0, 100, 28)
        };
        _regionPreview.ClientRegionChanged += OnOcrClientRegionChanged;
        RegionPreviewHost.Child = _regionPreview;
        UpdateOcrHint();
    }

    private void OnOcrClientRegionChanged(object? sender, CymbalOcrRegionChangedEventArgs e)
    {
        if (!_isLoadingState)
        {
            TrySaveState();
        }
    }

    private void OnWindowLoaded(object sender, RoutedEventArgs e)
    {
        nint h = (nint)new WindowInteropHelper(this).Handle;
        _cymbalToolWindowHandle = h;
        _isLoadingState = true;
        try
        {
            RestoreState();
        }
        finally
        {
            _isLoadingState = false;
        }
        if (OcrTargetCombo.Items.Count > 0 && OcrTargetCombo.SelectedItem is not null)
        {
            TryRefreshOcrBitmap();
        }
    }

    private void OnWindowClosing(object? sender, CancelEventArgs e)
    {
        TrySaveState();
    }

    private void RestoreState()
    {
        (CymbalAlternationStateDto? state, string? loadError) = CymbalAlternationStateStore.Load();
        if (loadError is not null)
        {
            ResultTextBox.Text = loadError;
            return;
        }

        if (state is null)
        {
            return;
        }

        if (state.MidiPath is { Length: > 0 } savedMidi)
        {
            MidiPathTextBox.Text = savedMidi;
        }

        if (state.StartTickText is { Length: > 0 } startText)
        {
            StartTickTextBox.Text = startText;
        }

        if (state.EndTickText is { Length: > 0 } endText)
        {
            EndTickTextBox.Text = endText;
        }

        _intervalItems.Clear();
        if (state.Intervals is not null)
        {
            foreach (CymbalIntervalDto entry in state.Intervals)
            {
                _intervalItems.Add(new TickIntervalItem(entry.Start, entry.End));
            }
        }

        if (state.OcrTarget is { } ocr)
        {
            if (ocr.Width > 0 && ocr.Height > 0)
            {
                _regionPreview.OcrClientRegion = new Rectangle(ocr.Left, ocr.Top, ocr.Width, ocr.Height);
            }

            RefillOcrTargetCombo(
                new CymbalOcrSessionSelection(ocr.TargetWindowTitle, ocr.TargetProcessName),
                ocr
            );
        }
        else
        {
            RefillOcrTargetCombo(null, null);
        }
    }

    private sealed class CymbalOcrSessionSelection
    {
        public CymbalOcrSessionSelection(string? title, string? process)
        {
            TargetWindowTitle = title;
            TargetProcessName = process;
        }

        public string? TargetWindowTitle { get; }

        public string? TargetProcessName { get; }
    }

    private void RefillOcrTargetCombo(
        CymbalOcrSessionSelection? trySelect,
        CymbalOcrStateDto? fromRestore)
    {
        IReadOnlyList<CymbalWindowOption> options = CymbalWindowEnumerator.GetVisibleTopLevelOptions(
            _cymbalToolWindowHandle == nint.Zero ? null : _cymbalToolWindowHandle
        );

        OcrTargetCombo.ItemsSource = null;
        OcrTargetCombo.ItemsSource = options;

        CymbalWindowOption? toSelect = null;
        if (trySelect is not null && !string.IsNullOrWhiteSpace(trySelect.TargetWindowTitle))
        {
            toSelect = CymbalWindowEnumerator.FindOptionByTitle(
                options,
                trySelect.TargetWindowTitle!,
                trySelect.TargetProcessName
            );
        }
        else if (fromRestore is { TargetWindowTitle: { Length: > 0 } t })
        {
            toSelect = CymbalWindowEnumerator.FindOptionByTitle(
                options,
                t,
                fromRestore.TargetProcessName
            );
        }

        if (toSelect is { Handle: not 0 } found)
        {
            SetComboSelectionByWindowHandle(options, found.Handle);
        }
    }

    private void SetComboSelectionByWindowHandle(IReadOnlyList<CymbalWindowOption> options, nint handle)
    {
        IReadOnlyList<CymbalWindowOption> asList = options;
        for (int i = 0; i < asList.Count; i++)
        {
            if (asList[i].Handle == handle)
            {
                OcrTargetCombo.SelectedIndex = i;
                return;
            }
        }
    }

    private void TrySaveState()
    {
        if (_isLoadingState)
        {
            return;
        }

        var state = new CymbalAlternationStateDto
        {
            MidiPath = MidiPathTextBox.Text,
            StartTickText = StartTickTextBox.Text,
            EndTickText = EndTickTextBox.Text,
            Intervals = _intervalItems
                .Select(
                    item => new CymbalIntervalDto
                    {
                        Start = item.StartTick,
                        End = item.EndTick
                    }
                )
                .ToList()
        };

        if (OcrTargetCombo.SelectedItem is CymbalWindowOption selected)
        {
            Rectangle r = _regionPreview.OcrClientRegion;
            state.OcrTarget = new CymbalOcrStateDto
            {
                TargetWindowTitle = selected.Title,
                TargetProcessName = selected.ProcessName,
                Left = r.X,
                Top = r.Y,
                Width = r.Width,
                Height = r.Height
            };
        }

        try
        {
            CymbalAlternationStateStore.Save(state);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                "Could not save your cymbal tool session. " + ex.Message,
                "Cymbal session",
                MessageBoxButton.OK,
                MessageBoxImage.Warning
            );
        }
    }

    private void OnRefreshWindowListClick(object sender, RoutedEventArgs e)
    {
        CymbalWindowOption? current = OcrTargetCombo.SelectedItem is CymbalWindowOption o ? o : null;
        RefillOcrTargetCombo(
            current is { } c ? new CymbalOcrSessionSelection(c.Title, c.ProcessName) : null,
            null
        );
    }

    private void OnOcrTargetChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_isLoadingState)
        {
            return;
        }

        TrySaveState();
    }

    private void OnOcrDrawRegionToggled(object sender, RoutedEventArgs e)
    {
        _regionPreview.EditMode = OcrDrawRegionCheck.IsChecked == true
            ? CymbalOcrEditMode.Draw
            : CymbalOcrEditMode.None;
    }

    private void OnRefreshOcrPreviewClick(object sender, RoutedEventArgs e)
    {
        TryRefreshOcrBitmap();
    }

    private void TryRefreshOcrBitmap()
    {
        if (OcrTargetCombo.SelectedItem is not CymbalWindowOption w)
        {
            ResultTextBox.Text = "Select a target window first.";
            return;
        }

        if (CymbalClientBitmapCapture.TryCaptureClientBitmap(w.Handle) is { } cap)
        {
            _regionPreview.PreviewBitmap = cap;
        }
    }

    private async void OnOcrReadClick(object sender, RoutedEventArgs e)
    {
        if (OcrTargetCombo.SelectedItem is not CymbalWindowOption w)
        {
            ResultTextBox.Text = "Select a target window.";
            return;
        }

        if (_regionPreview.OcrClientRegion.Width < 4 || _regionPreview.OcrClientRegion.Height < 4)
        {
            ResultTextBox.Text = "Draw a larger OCR region (check \"Draw OCR region\").";
            return;
        }

        if (CymbalClientBitmapCapture.TryCaptureClientBitmap(w.Handle) is not { } full)
        {
            ResultTextBox.Text = "Could not capture that window.";
            return;
        }

        OcrReadButton.IsEnabled = false;
        try
        {
            using (full)
            {
                if (CymbalBitmapCrop.CropToRegion(full, _regionPreview.OcrClientRegion) is not { } crop)
                {
                    return;
                }

                using (crop)
                {
                    long? n = await CymbalOcrService
                        .TryReadTickNumberFromBitmapAsync(crop, CancellationToken.None)
                        .ConfigureAwait(true);
                    if (n is not { } tick)
                    {
                        ResultTextBox.Text = "OCR did not find a number. Adjust region or zoom.";
                        return;
                    }

                    ApplyOcrTick(tick);
                }
            }
        }
        finally
        {
            OcrReadButton.IsEnabled = true;
        }
    }

    private void UpdateOcrHint()
    {
        if (_nextOcrFillsStart)
        {
            OcrFieldHintText.Text =
                "Next read fills Start. Then read again for End (the pair is auto-added to the list).";
        }
        else
        {
            OcrFieldHintText.Text =
                "Next read fills End, then the interval is appended and the next read goes to Start again.";
        }
    }

    private void ApplyOcrTick(long tick)
    {
        if (_nextOcrFillsStart)
        {
            StartTickTextBox.Text = tick.ToString(CultureInfo.InvariantCulture);
            _nextOcrFillsStart = false;
            ResultTextBox.Text = "OCR: Start = " + tick;
        }
        else
        {
            EndTickTextBox.Text = tick.ToString(CultureInfo.InvariantCulture);
            ResultTextBox.Text = "OCR: End = " + tick;
            TryAutocommitIntervalFromFields();
        }

        UpdateOcrHint();
        TrySaveState();
    }

    private void TryAutocommitIntervalFromFields()
    {
        if (!long.TryParse(StartTickTextBox.Text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out long startT))
        {
            return;
        }

        if (!long.TryParse(EndTickTextBox.Text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out long endT))
        {
            return;
        }

        if (startT < 0)
        {
            return;
        }

        if (endT < startT)
        {
            ResultTextBox.Text = "OCR: End is before Start. Fix the fields or re-read.";
            return;
        }

        bool already = _intervalItems.Any(i => i.StartTick == startT && i.EndTick == endT);
        if (already)
        {
            _nextOcrFillsStart = true;
            StartTickTextBox.Text = "0";
            EndTickTextBox.Text = "0";
            UpdateOcrHint();
            ResultTextBox.Text = "Interval " + startT + " to " + endT + " already in list. Cleared; next OCR = Start.";
            return;
        }

        _intervalItems.Add(new TickIntervalItem(startT, endT));
        _nextOcrFillsStart = true;
        StartTickTextBox.Text = "0";
        EndTickTextBox.Text = "0";
        UpdateOcrHint();
        ResultTextBox.Text = "Added interval: " + startT + " \u2013 " + endT + ". Next OCR = Start.";
    }

    private void OnBrowseMidiClick(object sender, RoutedEventArgs e)
    {
        var dialog = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select MIDI file",
            Filter = "MIDI files (*.mid)|*.mid|All files (*.*)|*.*",
            CheckFileExists = true,
            Multiselect = false
        };
        if (dialog.ShowDialog(this) == true)
        {
            MidiPathTextBox.Text = dialog.FileName;
            TrySaveState();
        }
    }

    private void OnApplyAlternationClick(object sender, RoutedEventArgs e)
    {
        try
        {
            string midiPath = (MidiPathTextBox.Text ?? string.Empty).Trim();
            if (midiPath.Length == 0)
            {
                throw new InvalidOperationException("Please select a MIDI file.");
            }

            if (_intervalItems.Count == 0)
            {
                throw new InvalidOperationException("Add at least one tick interval (manually or via OCR).");
            }

            ExecuteButton.IsEnabled = false;
            IReadOnlyList<(long start, long end)> tickRanges = _intervalItems
                .Select(interval => (interval.StartTick, interval.EndTick))
                .ToList();
            CymbalAlternationResult res = CymbalAlternationService.ApplyAlternation(
                midiPath: midiPath,
                intervals: tickRanges
            );

            var b = new StringBuilder();
            b.AppendLine("Alternation completed.");
            b.AppendLine("File: " + res.MidiPath);
            b.AppendLine("Backup: " + res.BackupFilePath);
            b.AppendLine("Intervals: " + res.IntervalCount);
            b.AppendLine("Combined tick range: " + res.StartTick + " to " + res.EndTick);
            b.AppendLine("Candidate cymbal notes: " + res.CandidateCount);
            b.AppendLine("Removed notes: " + res.RemovedCount);
            ResultTextBox.Text = b.ToString();
            TrySaveState();
        }
        catch (Exception ex)
        {
            ResultTextBox.Text = "Error: " + ex.Message;
        }
        finally
        {
            ExecuteButton.IsEnabled = true;
        }
    }

    private void OnAddIntervalClick(object sender, RoutedEventArgs e)
    {
        try
        {
            if (!long.TryParse(StartTickTextBox.Text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out long st))
            {
                throw new InvalidOperationException("Start tick must be an integer.");
            }

            if (!long.TryParse(EndTickTextBox.Text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out long et))
            {
                throw new InvalidOperationException("End tick must be an integer.");
            }

            if (st < 0)
            {
                throw new InvalidOperationException("Start tick must be non-negative.");
            }

            if (et < st)
            {
                throw new InvalidOperationException("End tick must be >= start tick.");
            }

            if (_intervalItems.Any(i => i.StartTick == st && i.EndTick == et))
            {
                throw new InvalidOperationException("This interval is already in the list.");
            }

            _intervalItems.Add(new TickIntervalItem(st, et));
            ResultTextBox.Text = "Interval added: " + st + " to " + et;
            TrySaveState();
        }
        catch (Exception ex)
        {
            ResultTextBox.Text = "Error: " + ex.Message;
        }
    }

    private void OnRemoveIntervalClick(object sender, RoutedEventArgs e)
    {
        if (IntervalsListBox.SelectedItem is not TickIntervalItem i)
        {
            ResultTextBox.Text = "Select an interval to remove.";
            return;
        }

        _ = _intervalItems.Remove(i);
        ResultTextBox.Text = "Removed: " + i;
        TrySaveState();
    }

    private void OnClearIntervalsClick(object sender, RoutedEventArgs e)
    {
        _intervalItems.Clear();
        _nextOcrFillsStart = true;
        UpdateOcrHint();
        ResultTextBox.Text = "Intervals cleared.";
        TrySaveState();
    }
}

internal sealed class TickIntervalItem
{
    internal TickIntervalItem(long startTick, long endTick)
    {
        StartTick = startTick;
        EndTick = endTick;
    }

    internal long StartTick { get; }

    internal long EndTick { get; }

    public override string ToString()
    {
        return "Start: " + StartTick + " | End: " + EndTick;
    }
}
