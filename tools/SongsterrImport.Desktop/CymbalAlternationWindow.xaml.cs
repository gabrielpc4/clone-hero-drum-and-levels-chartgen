using Microsoft.Win32;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Windows;

namespace SongsterrImport.Desktop;

public partial class CymbalAlternationWindow : Window
{
    private readonly ObservableCollection<TickIntervalItem> _intervalItems = new();

    private bool _isLoadingState;

    public CymbalAlternationWindow()
    {
        InitializeComponent();
        StartTickTextBox.Text = "0";
        EndTickTextBox.Text = "0";
        IntervalsListBox.ItemsSource = _intervalItems;
        StartTickTextBox.LostFocus += (_, __) => TrySaveState();
        EndTickTextBox.LostFocus += (_, __) => TrySaveState();
        MidiPathTextBox.LostFocus += (_, __) => TrySaveState();
    }

    private void OnWindowLoaded(object sender, RoutedEventArgs e)
    {
        _isLoadingState = true;
        try
        {
            RestoreState();
        }
        finally
        {
            _isLoadingState = false;
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
                .Select(item => new CymbalIntervalDto
                {
                    Start = item.StartTick,
                    End = item.EndTick
                })
                .ToList()
        };

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
                MessageBoxImage.Warning);
        }
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
        bool? result = dialog.ShowDialog(this);
        if (result == true)
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
                throw new InvalidOperationException("Please add at least one interval with the + button.");
            }

            ExecuteButton.IsEnabled = false;
            IReadOnlyList<(long start, long end)> tickRanges = _intervalItems
                .Select(interval => (interval.StartTick, interval.EndTick))
                .ToList();
            CymbalAlternationResult result = CymbalAlternationService.ApplyAlternation(
                midiPath: midiPath,
                intervals: tickRanges
            );

            var messageBuilder = new StringBuilder();
            messageBuilder.AppendLine("Alternation completed.");
            messageBuilder.AppendLine("File: " + result.MidiPath);
            messageBuilder.AppendLine("Backup: " + result.BackupFilePath);
            messageBuilder.AppendLine("Intervals: " + result.IntervalCount);
            messageBuilder.AppendLine("Combined tick range: " + result.StartTick + " to " + result.EndTick);
            messageBuilder.AppendLine("Candidate cymbal notes (all expert cymbals): " + result.CandidateCount);
            messageBuilder.AppendLine("Removed notes: " + result.RemovedCount);
            ResultTextBox.Text = messageBuilder.ToString();
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
            if (!long.TryParse(StartTickTextBox.Text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out long startTick))
            {
                throw new InvalidOperationException("Start tick must be an integer.");
            }

            if (!long.TryParse(EndTickTextBox.Text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out long endTick))
            {
                throw new InvalidOperationException("End tick must be an integer.");
            }

            if (startTick < 0)
            {
                throw new InvalidOperationException("Start tick must be >= 0.");
            }

            if (endTick < startTick)
            {
                throw new InvalidOperationException("End tick must be >= start tick.");
            }

            bool alreadyExists = _intervalItems.Any(interval => interval.StartTick == startTick && interval.EndTick == endTick);
            if (alreadyExists)
            {
                throw new InvalidOperationException("This interval is already in the list.");
            }

            _intervalItems.Add(new TickIntervalItem(startTick, endTick));
            ResultTextBox.Text = "Interval added: " + startTick + " to " + endTick;
            TrySaveState();
        }
        catch (Exception ex)
        {
            ResultTextBox.Text = "Error: " + ex.Message;
        }
    }

    private void OnRemoveIntervalClick(object sender, RoutedEventArgs e)
    {
        if (IntervalsListBox.SelectedItem is not TickIntervalItem selectedItem)
        {
            ResultTextBox.Text = "Error: Select an interval to remove.";
            return;
        }

        _intervalItems.Remove(selectedItem);
        ResultTextBox.Text = "Interval removed: " + selectedItem;
        TrySaveState();
    }

    private void OnClearIntervalsClick(object sender, RoutedEventArgs e)
    {
        _intervalItems.Clear();
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
