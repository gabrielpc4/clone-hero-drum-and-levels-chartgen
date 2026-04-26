// Author: Gabriel Pinheiro de Carvalho
using System.Diagnostics;
using System.Text;

namespace SongsterrImport.Desktop;

internal static class ProcessRunner
{
    internal static async Task<int> RunWithLogAsync(
        string fileName,
        IReadOnlyList<string> argumentList,
        string? workingDirectory,
        IReadOnlyDictionary<string, string>? environment,
        IProgress<string> log,
        CancellationToken cancellationToken
    )
    {
        var psi = new ProcessStartInfo
        {
            FileName = fileName,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };

        if (workingDirectory is not null)
        {
            psi.WorkingDirectory = workingDirectory;
        }

        if (environment is not null)
        {
            foreach (var pair in environment)
            {
                psi.Environment[pair.Key] = pair.Value;
            }
        }

        foreach (var a in argumentList)
        {
            psi.ArgumentList.Add(a);
        }

        using var process = new Process { StartInfo = psi, EnableRaisingEvents = true };

        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data is not null)
            {
                log.Report(e.Data);
            }
        };

        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is not null)
            {
                log.Report("stderr: " + e.Data);
            }
        };

        if (!process.Start())
        {
            log.Report("Failed to start process: " + fileName);
            return -1;
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        await using var _ = cancellationToken.Register(
            static pr =>
            {
                try
                {
                    if (pr is Process p and { HasExited: false })
                    {
                        p.Kill(entireProcessTree: true);
                    }
                }
                catch
                {
                    // ignored
                }
            },
            process);
        try
        {
            await process.WaitForExitAsync(cancellationToken);
        }
        catch (OperationCanceledException)
        {
            log.Report("Canceled.");
            return -1;
        }

        return process.ExitCode;
    }
}
