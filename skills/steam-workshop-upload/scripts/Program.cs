using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace KleiWorkshopUploader;

internal static class Program
{
    private static int Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        if (args.Length == 1 && args[0] is "--help" or "-h")
        {
            Console.WriteLine("WorkshopUpload <plan|check|inspect|list|upload> <job.json|query.json>");
            return 0;
        }
        if (args.Length != 2 || args[0] is not ("plan" or "check" or "inspect" or "list" or "upload"))
        {
            Console.Error.WriteLine("用法：WorkshopUpload <plan|check|inspect|list|upload> <job.json|query.json>");
            return 2;
        }
        try
        {
            if (args[0] == "list") { PublishedList.Run(args[1]); return 0; }
            var context = new JobContext(args[1]);
            switch (args[0])
            {
                case "plan": Planner.Create(context); return 0;
                case "check": Planner.Check(context); return 0;
                case "inspect": Inspect(context); return 0;
                default: return Upload(context);
            }
        }
        catch (TargetConfirmationRequired exception)
        {
            Console.Error.WriteLine("等待用户确认：" + exception.Message);
            return 4;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine("失败：" + exception.Message);
            return 1;
        }
    }

    private static SteamworksWorkshopUploader Uploader() => new(AppContext.BaseDirectory);
    private static void Log(string message) => Console.WriteLine($"[{DateTimeOffset.Now:HH:mm:ss}] {message}");

    private static void Inspect(JobContext context)
    {
        if (context.PublishedId == 0) throw new ArgumentException("inspect 需要一个已有的 workshop_id。");
        WorkshopPublishedItem item = Uploader().GetPublishedItem(context.Job.AppId, context.PublishedId, Log)
            ?? throw new InvalidOperationException("找不到工坊物品，或当前账号无权查询。");
        var details = new
        {
            WorkshopId = item.PublishedFileId.ToString(),
            item.AppId,
            OwnerSteamId = item.OwnerSteamId.ToString(),
            item.Title,
            item.Description,
            item.Tags,
            item.TagsLoaded,
            item.Version,
            item.TimeUpdated,
            item.Visibility,
            item.PreviewUrl
        };
        string path = Path.ChangeExtension(context.ConfigPath, ".inspect.json");
        JobContext.WriteJson(path, details);
        Console.WriteLine(JsonSerializer.Serialize(details, JobContext.JsonOptions));
        Console.WriteLine("只读查询已写入：" + path);
    }

    private static int Upload(JobContext context)
    {
        context.RequireConfirmedTarget();
        UploadPlan plan = Planner.Check(context);
        UploadJob job = context.Job;
        if (job.Operation == "create" && File.Exists(context.ResultPath))
            throw new InvalidOperationException("此创建任务已有执行回执。先检查回执和 Steam 工坊；已有 ID 时改为 update，避免重复创建。");

        var uploader = Uploader();
        WorkshopPublishedItem before = null;
        if (context.PublishedId != 0)
        {
            before = uploader.GetPublishedItem(job.AppId, context.PublishedId, Log)
                ?? throw new InvalidOperationException("无法读取上传前的工坊状态，已停止。");
            if (job.UpdateContent && !job.Force && (string.IsNullOrWhiteSpace(before.Version) || before.Version.Trim() == plan.Version))
                throw new InvalidOperationException("工坊旧版本未知或与本地 version 相同。先确认目标并递增版本；明确需要覆盖时设置 force=true 后重新 plan。");
        }

        var item = new WorkshopUploadItem
        {
            AppId = job.AppId,
            PublishedFileId = context.PublishedId,
            ContentFolder = plan.PayloadDirectory ?? "",
            PreviewFile = job.UpdatePreview ? context.Resolve(job.PreviewFile) : "",
            Visibility = job.Visibility ?? before?.Visibility ?? 2,
            Title = job.Title,
            Description = string.IsNullOrWhiteSpace(job.DescriptionFile) ? job.Description : File.ReadAllText(context.Resolve(job.DescriptionFile)),
            Version = plan.Version,
            VersionCompatible = plan.VersionCompatible,
            ChangeNote = job.AppId == 219740 ? "" : job.ChangeNote,
            UpdateContent = job.UpdateContent,
            UpdatePreview = job.UpdatePreview,
            UpdateMetadata = job.UpdateMetadata,
            UpdateTags = job.UpdateTags,
            UpdateVersionMetadata = job.AppId == 322330 && (job.UpdateMetadata || job.UpdateContent && job.UpdateVersionMetadata) && !string.IsNullOrWhiteSpace(plan.Version),
            // The snapshot has already applied the user's selection and official filters.
            UploadRedundantFiles = true
        };
        bool syncVersion = item.UpdateVersionMetadata || job.AppId == 219740 && (job.UpdateContent || job.UpdateMetadata);
        item.UpdateTags |= syncVersion;
        if (item.UpdateTags || item.UpdateMetadata)
        {
            if (before != null && job.Tags == null && !before.TagsLoaded)
                throw new InvalidOperationException("无法读取已有 Tags；为避免覆盖，先检查工坊或显式提供完整 tags 数组。");
            IEnumerable<string> tags = job.Tags ?? (before?.Tags ?? "").Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
            item.Tags = BuildTags(tags, plan, job, syncVersion, File.ReadAllText(Path.Combine(context.SourceRoot, "modinfo.lua")));
        }

        // Querying Steam may take time. Recheck immediately before any write.
        Planner.Check(context);
        string logPath = Path.ChangeExtension(context.ConfigPath, ".upload.log");
        ulong resultingId = context.PublishedId;
        bool submitted = false;
        string phase = "started";
        void Save(string status, string message = "") => JobContext.WriteJson(context.ResultPath, new
        {
            Status = status,
            Operation = job.Operation,
            AppId = job.AppId,
            WorkshopId = resultingId.ToString(),
            Version = plan.Version,
            ConfigSha256 = plan.ConfigSha256,
            Submitted = submitted,
            Phase = phase,
            TimeUtc = DateTime.UtcNow,
            Message = message,
            WorkshopUrl = resultingId == 0 ? "" : "https://steamcommunity.com/sharedfiles/filedetails/?id=" + resultingId
        });
        void UploadLog(string message)
        {
            Log(message);
            File.AppendAllText(logPath, $"[{DateTimeOffset.Now:O}] {message}{Environment.NewLine}", new UTF8Encoding(false));
        }
        uploader.ItemCreated = id => { resultingId = id; phase = "created"; Save("created_pending"); };
        Save("started");
        try
        {
            UploadLog($"执行 {job.Operation}，目标 {job.AppId}/{job.WorkshopId}，{plan.Files.Count} 个文件，version={plan.Version}");
            WorkshopUploadResult result = uploader.Upload(item, UploadLog);
            resultingId = result.PublishedFileId;
            submitted = true;
            phase = result.SubmissionUncertain ? "callback_uncertain" : "submitted";
            Save("submitted_unverified");
            if (result.UserNeedsToAcceptWorkshopLegalAgreement)
            {
                Save("needs_legal_agreement", "Steam 要求接受创意工坊协议；请先处理协议并查询实际结果。");
                return 3;
            }
            Verify(uploader, item, resultingId, before, UploadLog);
            phase = "verified";
            Save("verified");
            UploadLog("上传并复查成功，工坊 ID=" + resultingId);
            return 0;
        }
        catch (Exception exception)
        {
            Save(submitted ? "submitted_unverified" : "failed_or_uncertain", exception.Message);
            throw;
        }
    }

    private static string[] BuildTags(IEnumerable<string> original, UploadPlan plan, UploadJob job, bool syncVersion, string lua)
    {
        var tags = original.Where(t => !string.IsNullOrWhiteSpace(t)).Select(t => t.Trim()).ToList();
        if (syncVersion)
        {
            tags.RemoveAll(t => Regex.IsMatch(t, @"^version(?:_compatible)?\s*[:=]", RegexOptions.IgnoreCase));
            if (!string.IsNullOrWhiteSpace(plan.Version)) tags.Add("version:" + plan.Version);
            if (job.AppId == 322330 && !string.IsNullOrWhiteSpace(plan.VersionCompatible)) tags.Add("version_compatible:" + plan.VersionCompatible);
        }
        if (job.AppId == 219740 && (job.UpdateContent || job.UpdateMetadata))
        {
            tags.RemoveAll(t => t is "Reign of Giants Compatible" or "Shipwrecked Compatible" or "Hamlet Compatible");
            tags.Add("item");
            foreach (var pair in new[] { ("reign_of_giants_compatible", "Reign of Giants Compatible"), ("shipwrecked_compatible", "Shipwrecked Compatible"), ("hamlet_compatible", "Hamlet Compatible") })
                if (ModInfo.ReadLuaBoolField(lua, pair.Item1)) tags.Add(pair.Item2);
        }
        return tags.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    }

    private static void Verify(SteamworksWorkshopUploader uploader, WorkshopUploadItem expected, ulong id, WorkshopPublishedItem before, Action<string> log)
    {
        string reason = "工坊尚未返回新状态";
        for (int attempt = 1; attempt <= 3; attempt++)
        {
            try
            {
                WorkshopPublishedItem current = uploader.GetPublishedItem(expected.AppId, id, log);
                if (current == null) reason = "未找到物品";
                else if (before != null && current.TimeUpdated <= before.TimeUpdated) reason = "工坊更新时间尚未推进";
                else if ((expected.UpdateVersionMetadata || expected.UpdateTags && expected.Tags?.Any(t => t.StartsWith("version:")) == true) && current.Version?.Trim() != expected.Version?.Trim()) reason = "工坊版本尚未同步";
                else if (current.Visibility != expected.Visibility) reason = "可见性尚未同步";
                else if (expected.UpdateTags && (!current.TagsLoaded || !expected.Tags.All(t => (current.Tags ?? "").Split(',', StringSplitOptions.TrimEntries).Contains(t, StringComparer.OrdinalIgnoreCase)))) reason = "Tags 尚未同步";
                else { log("二次检查通过：更新时间=" + current.TimeUpdated + "，版本=" + current.Version); return; }
            }
            catch (Exception exception) { reason = exception.Message; }
            log($"复查 {attempt}/3：{reason}");
            if (attempt < 3) Thread.Sleep(5000);
        }
        throw new InvalidOperationException("上传已返回，但未能确认生效：" + reason + "。先 inspect/检查工坊，不要自动重复提交。");
    }
}
