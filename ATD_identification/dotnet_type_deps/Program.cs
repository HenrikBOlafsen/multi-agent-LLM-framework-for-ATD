using System.Text.Json;
using Microsoft.Build.Locator;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.MSBuild;

namespace DotnetTypeDeps;

internal static class Program
{
    private static string Norm(string p) => Path.GetFullPath(p).Replace('\\', '/');

    private static bool IsUnder(string path, string root)
    {
        path = Norm(path).TrimEnd('/');
        root = Norm(root).TrimEnd('/');
        return path == root || path.StartsWith(root + "/", StringComparison.OrdinalIgnoreCase);
    }

    private static bool ShouldIgnoreFile(string absPath)
    {
        var p = Norm(absPath);
        if (p.Contains("/bin/", StringComparison.OrdinalIgnoreCase)) return true;
        if (p.Contains("/obj/", StringComparison.OrdinalIgnoreCase)) return true;
        if (p.EndsWith(".g.cs", StringComparison.OrdinalIgnoreCase)) return true;
        if (p.EndsWith(".designer.cs", StringComparison.OrdinalIgnoreCase)) return true;
        if (p.EndsWith(".assemblyinfo.cs", StringComparison.OrdinalIgnoreCase)) return true;
        return false;
    }

    private static IEnumerable<TypeSyntax> CollectTypeSyntaxNodes(SyntaxNode root) =>
        root.DescendantNodes().OfType<TypeSyntax>();

    private static IEnumerable<AttributeSyntax> CollectAttributeNodes(SyntaxNode root) =>
        root.DescendantNodes().OfType<AttributeSyntax>();

    private static HashSet<string> DeclaringSourceFiles(ITypeSymbol typeSym)
    {
        var outFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        // Recurse into generic type arguments to catch List<User> => User
        if (typeSym is INamedTypeSymbol nts && nts.TypeArguments.Length > 0)
        {
            foreach (var ta in nts.TypeArguments)
            {
                if (ta is ITypeSymbol ts)
                {
                    foreach (var f in DeclaringSourceFiles(ts))
                        outFiles.Add(f);
                }
            }
        }

        var baseSym = (typeSym as INamedTypeSymbol)?.OriginalDefinition ?? typeSym;

        foreach (var sr in baseSym.DeclaringSyntaxReferences)
        {
            var fp = sr.SyntaxTree?.FilePath;
            if (!string.IsNullOrWhiteSpace(fp))
                outFiles.Add(Norm(fp));
        }

        return outFiles;
    }

    private static int ExitWith(string msg, int code)
    {
        Console.Error.WriteLine("ERROR: " + msg);
        return code;
    }

    private static string? GetArg(string[] args, string name)
    {
        for (var i = 0; i < args.Length; i++)
        {
            if (args[i] == name && i + 1 < args.Length)
                return args[i + 1];
        }
        return null;
    }

    private static string? PickSolutionOrProject(string repoRoot, string entryAbs, string? slnArg, string? csprojArg)
    {
        if (!string.IsNullOrWhiteSpace(slnArg))
            return Norm(Path.IsPathRooted(slnArg) ? slnArg : Path.Combine(repoRoot, slnArg));

        if (!string.IsNullOrWhiteSpace(csprojArg))
            return Norm(Path.IsPathRooted(csprojArg) ? csprojArg : Path.Combine(repoRoot, csprojArg));

        // Prefer a .sln under repo root
        var slns = Directory.GetFiles(repoRoot, "*.sln", SearchOption.AllDirectories)
            .Where(p => !p.Contains("/.git/", StringComparison.OrdinalIgnoreCase))
            .OrderBy(p => p.Length)
            .ToList();

        if (slns.Count > 0) return Norm(slns[0]);

        // Fallback: any csproj under entry
        var projs = Directory.GetFiles(entryAbs, "*.csproj", SearchOption.AllDirectories)
            .Where(p => !ShouldIgnoreFile(p))
            .OrderBy(p => p.Length)
            .ToList();

        if (projs.Count > 0) return Norm(projs[0]);

        return null;
    }

    public static async Task<int> Main(string[] args)
    {
        var repoRootArg = GetArg(args, "--repo-root");
        var entryArg = GetArg(args, "--entry");
        var outPathArg = GetArg(args, "--out");
        var slnArg = GetArg(args, "--sln");
        var csprojArg = GetArg(args, "--csproj");

        if (repoRootArg is null || entryArg is null || outPathArg is null)
        {
            return ExitWith("Usage: --repo-root <path> --entry <subdir> --out <file> [--sln <file>|--csproj <file>]", 2);
        }

        var repoRoot = Norm(repoRootArg);
        var entryAbs = Norm(Path.Combine(repoRoot, entryArg.TrimEnd('/', '\\')));
        var outPath = Norm(outPathArg);

        if (!Directory.Exists(repoRoot)) return ExitWith($"Repo root not found: {repoRoot}", 3);
        if (!Directory.Exists(entryAbs)) return ExitWith($"Entry not found: {entryAbs}", 3);

        // MSBuild registration
        if (!MSBuildLocator.IsRegistered)
        {
            var vs = MSBuildLocator.QueryVisualStudioInstances().OrderByDescending(x => x.Version).FirstOrDefault();
            if (vs is not null) MSBuildLocator.RegisterInstance(vs);
            else MSBuildLocator.RegisterDefaults();
        }

        var target = PickSolutionOrProject(repoRoot, entryAbs, slnArg, csprojArg);
        if (target is null) return ExitWith("Could not find a .sln or .csproj to analyze. Use --sln or --csproj.", 4);

        Console.WriteLine($"Repo    : {repoRoot}");
        Console.WriteLine($"Entry   : {entryArg} ({entryAbs})");
        Console.WriteLine($"Target  : {target}");
        Console.WriteLine($"Out     : {outPath}");
        Console.WriteLine();

        bool AcceptSourceFile(string absPath)
        {
            if (string.IsNullOrWhiteSpace(absPath)) return false;
            absPath = Norm(absPath);
            if (!absPath.EndsWith(".cs", StringComparison.OrdinalIgnoreCase)) return false;
            if (!IsUnder(absPath, repoRoot)) return false;
            if (!IsUnder(absPath, entryAbs)) return false;
            if (ShouldIgnoreFile(absPath)) return false;
            return true;
        }

        string RepoRel(string absPath)
        {
            var rel = Path.GetRelativePath(repoRoot, absPath);
            return rel.Replace('\\', '/');
        }

        var workspace = MSBuildWorkspace.Create();
        workspace.WorkspaceFailed += (_, __) => { /* noisy but usually fine */ };

        Solution solution;
        try
        {
            if (target.EndsWith(".sln", StringComparison.OrdinalIgnoreCase))
                solution = await workspace.OpenSolutionAsync(target);
            else
                solution = (await workspace.OpenProjectAsync(target)).Solution;
        }
        catch (Exception ex)
        {
            return ExitWith($"Failed to load solution/project: {ex.Message}", 5);
        }

        var fileIdToAbs = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var edges = new HashSet<(string s, string t)>();

        // Pre-register candidate docs
        foreach (var proj in solution.Projects)
        {
            foreach (var doc in proj.Documents)
            {
                var fp = doc.FilePath;
                if (fp is null) continue;
                fp = Norm(fp);
                if (!AcceptSourceFile(fp)) continue;

                var id = RepoRel(fp);
                fileIdToAbs[id] = fp;
            }
        }

        foreach (var proj in solution.Projects)
        {
            Compilation? compilation;
            try
            {
                compilation = await proj.GetCompilationAsync();
            }
            catch
            {
                continue;
            }

            if (compilation is null) continue;

            foreach (var tree in compilation.SyntaxTrees)
            {
                var srcAbs = tree.FilePath;
                if (string.IsNullOrWhiteSpace(srcAbs)) continue;
                srcAbs = Norm(srcAbs);

                if (!AcceptSourceFile(srcAbs)) continue;

                var srcId = RepoRel(srcAbs);
                fileIdToAbs[srcId] = srcAbs;

                var model = compilation.GetSemanticModel(tree, ignoreAccessibility: true);
                var root = await tree.GetRootAsync();

                // Type mentions
                foreach (var typeNode in CollectTypeSyntaxNodes(root))
                {
                    var ti = model.GetTypeInfo(typeNode);
                    var typeSym = ti.Type;
                    if (typeSym is null) continue;
                    if (typeSym.TypeKind == TypeKind.Error) continue;
                    if (typeSym.SpecialType == SpecialType.System_Object && typeNode.ToString() == "dynamic") continue;

                    foreach (var depAbs in DeclaringSourceFiles(typeSym))
                    {
                        if (!AcceptSourceFile(depAbs)) continue;
                        var depId = RepoRel(depAbs);
                        if (depId == srcId) continue;
                        edges.Add((srcId, depId));
                        fileIdToAbs[depId] = depAbs;
                    }
                }

                // Attributes (safety net)
                foreach (var attr in CollectAttributeNodes(root))
                {
                    var ti = model.GetTypeInfo(attr);
                    var typeSym = ti.Type;
                    if (typeSym is null) continue;
                    if (typeSym.TypeKind == TypeKind.Error) continue;

                    foreach (var depAbs in DeclaringSourceFiles(typeSym))
                    {
                        if (!AcceptSourceFile(depAbs)) continue;
                        var depId = RepoRel(depAbs);
                        if (depId == srcId) continue;
                        edges.Add((srcId, depId));
                        fileIdToAbs[depId] = depAbs;
                    }
                }
            }
        }

        var nodes = fileIdToAbs
            .OrderBy(kv => kv.Key, StringComparer.OrdinalIgnoreCase)
            .Select(kv => new Dictionary<string, object?>
            {
                ["id"] = kv.Key,
                ["kind"] = "file",
                ["abs_path"] = kv.Value
            })
            .ToList();

        var edgeRows = edges
            .OrderBy(e => e.s, StringComparer.OrdinalIgnoreCase)
            .ThenBy(e => e.t, StringComparer.OrdinalIgnoreCase)
            .Select(e => new Dictionary<string, object?>
            {
                ["source"] = e.s,
                ["target"] = e.t,
                ["relation"] = "type_ref"
            })
            .ToList();

        var payload = new Dictionary<string, object?>
        {
            ["schema_version"] = 1,
            ["language"] = "csharp",
            ["repo_root"] = repoRoot,
            ["entry"] = entryArg.TrimEnd('/', '\\'),
            ["nodes"] = nodes,
            ["edges"] = edgeRows
        };

        Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);

        await File.WriteAllTextAsync(
            outPath,
            JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true })
        );

        Console.WriteLine($"Wrote: {outPath} (nodes={nodes.Count} edges={edgeRows.Count})");
        return 0;
    }
}
