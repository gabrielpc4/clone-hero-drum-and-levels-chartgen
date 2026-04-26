using Microsoft.Win32;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Windows;

namespace SongsterrImport.Desktop;

public partial class CymbalAlternationWindow : Window
{
    private readonly ObservableCollection<TickIntervalItem> _intervalItems = new();

    public CymbalAlternationWindow()
    {
        InitializeComponent();
        CymbalComboBox.ItemsSource = new[]
        {
            CymbalType.Yellow,
            CymbalType.Blue,
            CymbalType.Green
        };
        CymbalComboBox.SelectedItem = CymbalType.Yellow;
        StartTickTextBox.Text = "0";
        EndTickTextBox.Text = "0";
        IntervalsListBox.ItemsSource = _intervalItems;
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
            IReadOnlyList<(CymbalType Cymbal, long Start, long End)> withCymbals = _intervalItems
                .Select(interval => (interval.Cymbal, interval.StartTick, interval.EndTick))
                .ToList();
            string cymbalsLine = string.Join(
                ", ",
                withCymbals
                    .Select(x => x.Cymbal)
                    .Distinct()
                    .Select(CymbalAlternationFormat.FormatCymbal)
                    .OrderBy(name => name));
            CymbalAlternationResult result = CymbalAlternationService.ApplyAlternation(
                midiPath: midiPath,
                intervals: withCymbals
            );

            var messageBuilder = new StringBuilder();
            messageBuilder.AppendLine("Alternation completed.");
            messageBuilder.AppendLine("File: " + result.MidiPath);
            messageBuilder.AppendLine("Cymbals in intervals: " + cymbalsLine);
            messageBuilder.AppendLine("Intervals: " + result.IntervalCount);
            messageBuilder.AppendLine("Combined tick range: " + result.StartTick + " to " + result.EndTick);
            messageBuilder.AppendLine("Candidate cymbal notes: " + result.CandidateCount);
            messageBuilder.AppendLine("Removed notes: " + result.RemovedCount);
            ResultTextBox.Text = messageBuilder.ToString();
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
            if (CymbalComboBox.SelectedItem is not CymbalType defaultCymbal)
            {
                throw new InvalidOperationException("Please select a cymbal for the new interval.");
            }

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

            bool alreadyExists = _intervalItems.Any(interval => interval.Cymbal == defaultCymbal
                && interval.StartTick == startTick
                && interval.EndTick == endTick);
            if (alreadyExists)
            {
                throw new InvalidOperationException("This interval is already in the list.");
            }

            _intervalItems.Add(new TickIntervalItem(defaultCymbal, startTick, endTick));
            ResultTextBox.Text = "Interval added: " + CymbalAlternationFormat.FormatCymbal(defaultCymbal) + " " + startTick + " to " + endTick;
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
    }

}

internal sealed class TickIntervalItem
{
    internal TickIntervalItem(CymbalType cymbal, long startTick, long endTick)
    {
        Cymbal = cymbal;
        StartTick = startTick;
        EndTick = endTick;
    }

    internal CymbalType Cymbal { get; }

    internal long StartTick { get; }

    internal long EndTick { get; }

    public override string ToString()
    {
        return CymbalAlternationFormat.FormatCymbal(Cymbal) + " | Start: " + StartTick + " | End: " + EndTick;
    }
}

internal static class CymbalAlternationFormat
{
    internal static string FormatCymbal(CymbalType cymbalType)
    {
        if (cymbalType == CymbalType.Yellow)
        {
            return "yellow";
        }

        if (cymbalType == CymbalType.Blue)
        {
            return "blue";
        }

        if (cymbalType == CymbalType.Green)
        {
            return "green";
        }

        return cymbalType.ToString();
    }
}
