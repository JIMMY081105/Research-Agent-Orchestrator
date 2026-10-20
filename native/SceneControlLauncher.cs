// C# 5 / .NET Framework. Stable, windowless entry; no model/network/task calls.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace BgvSceneControl
{
    internal static class Launcher
    {
        internal static string Resolve(out string activationHash, out string source)
        {
            var directory = Files.Safe(Path.Combine(Files.Runtime, "desktop"));
            var own = Files.Safe(Assembly.GetExecutingAssembly().Location);
            if (!String.Equals(own, Path.Combine(directory, "SceneControlLauncher.exe"), StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("LAUNCHER_LOCATION_INVALID");
            var receipt = Files.Read(Path.Combine(directory, "launcher.json"));
            var ownHash = Files.HashFile(own);
            if (!Object.Equals(receipt["owner"], Files.Owner) || !Object.Equals(receipt["sha256"], ownHash))
                throw new InvalidDataException("LAUNCHER_IDENTITY_INVALID");
            var activationPath = Files.Safe(Path.Combine(directory, "activation.json"));
            activationHash = Files.HashFile(activationPath);
            var activation = Files.Read(activationPath);
            var sha = activation.ContainsKey("sha256") ? activation["sha256"] as string : null;
            if (!Object.Equals(activation["owner"], Files.Owner) || sha == null || !Regex.IsMatch(sha, "^[0-9a-f]{64}$"))
                throw new InvalidDataException("ACTIVATION_IDENTITY_INVALID");
            var bundle = Files.Safe(Path.Combine(directory, "snapshots", sha));
            Files.VerifySnapshot(bundle, out source);
            if (!String.Equals(activation["source"] as string, source, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("ACTIVATION_SOURCE_INVALID");
            var manifest = Files.Read(Path.Combine(bundle, "manifest.json"));
            if (!Object.Equals(activation["source_sha256"], manifest["source_sha256"]))
                throw new InvalidDataException("ACTIVATION_SOURCE_HASH_INVALID");
            // A stable entry must itself be the exact launcher accepted in this snapshot.
            if (Files.HashFile(Path.Combine(bundle, "app", "SceneControlLauncher.exe")) != ownHash)
                throw new InvalidDataException("LAUNCHER_VERSION_MISMATCH");
            if (Files.HashFile(activationPath) != activationHash)
                throw new InvalidDataException("ACTIVATION_CHANGED_DURING_LAUNCH");
            return Files.Safe(Path.Combine(bundle, "app", "SceneControl.exe"));
        }
        internal static int Launch()
        {
            string activationHash, source;
            var executable = Resolve(out activationHash, out source);
            if (Files.HashFile(Path.Combine(Files.Runtime, "desktop", "activation.json")) != activationHash)
                throw new InvalidDataException("ACTIVATION_CHANGED_DURING_LAUNCH");
            using (var child = Process.Start(new ProcessStartInfo(executable) {
                WorkingDirectory = Path.GetDirectoryName(executable), UseShellExecute = false }))
            {
                var birth = child.StartTime.ToUniversalTime().ToFileTimeUtc().ToString();
                Files.Save(Path.Combine(Files.Runtime, "desktop", "launch.json"), new {
                    owner = Files.Owner, state = "STARTED", activation_sha256 = activationHash,
                    source = source, app = executable, pid = child.Id, birth = birth,
                    observed_at = DateTime.UtcNow.ToString("o"), model_calls = 0 });
            }
            return 0;
        }
        [STAThread]
        private static int Main(string[] args)
        {
            try
            {
                if (args.Length != 0) throw new InvalidDataException("LAUNCHER_ARGUMENTS_REJECTED");
                return Launch();
            }
            catch (Exception error)
            {
                // Fixed error codes only: no paths, environment, input, credentials or raw exceptions.
                var code = error is InvalidDataException && Regex.IsMatch(error.Message, "^[A-Z_]{1,80}$")
                    ? error.Message : "LAUNCHER_START_FAILED";
                MessageBox.Show("Scene Control could not start: " + code +
                    "\nCheck E: is available and use the installed shortcut. Existing tasks are unchanged.",
                    "Scene Control", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return 2;
            }
        }
    }
}
