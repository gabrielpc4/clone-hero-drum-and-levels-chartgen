using Microsoft.Win32;
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

            if (CymbalComboBox.SelectedItem is not CymbalType cymbalType)
            {
                throw new InvalidOperationException("Please select a cymbal.");
            }

            if (_intervalItems.Count == 0)
            {
                throw new InvalidOperationException("Please add at least one interval with the + button.");
            }

            ExecuteButton.IsEnabled = false;
            CymbalAlternationResult result = CymbalAlternationService.ApplyAlternation(
                midiPath: midiPath,
                cymbalType: cymbalType,
                intervals: _intervalItems
                    .Select(interval => (interval.StartTick, interval.EndTick))
                    .ToList()
            );

            var messageBuilder = new StringBuilder();
            messageBuilder.AppendLine("Alternation completed.");
            messageBuilder.AppendLine("File: " + result.MidiPath);
            messageBuilder.AppendLine("Cymbal: " + result.CymbalType);
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
        ResultTextBox.Text = "Interval removed: " + selectedItem.StartTick + " to " + selectedItem.EndTick;
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
