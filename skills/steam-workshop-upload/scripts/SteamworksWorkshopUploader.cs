// Steamworks upload/query core extracted from KleiWorkshopUploader v2.8 (MulanPSL-2.0).
// UI and deletion have been removed. Published-item discovery is read-only.
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

namespace KleiWorkshopUploader
{
    internal sealed class WorkshopUploadItem
    {
        public uint AppId;
        public ulong PublishedFileId;
        public string ContentFolder;
        public string PreviewFile;
        public int Visibility;
        public string Title;
        public string Description;
        public string[] Tags;
        public string Version;
        public string VersionCompatible;
        public string ChangeNote;
        public bool UpdateContent;
        public bool UpdatePreview;
        public bool UpdateMetadata;
        public bool UpdateTags;
        public bool UpdateVersionMetadata;
        public bool UploadRedundantFiles;
    }

    internal sealed class WorkshopUploadResult
    {
        public ulong PublishedFileId;
        public bool UserNeedsToAcceptWorkshopLegalAgreement;
        public bool SubmissionUncertain;
    }

    internal sealed class WorkshopPublishedItem
    {
        public ulong PublishedFileId;
        public uint AppId;
        public ulong OwnerSteamId;
        public string Title;
        public string Description;
        public string TitleChinese;
        public string DescriptionChinese;
        public string TitleEnglish;
        public string DescriptionEnglish;
        public string Tags;
        public bool TagsLoaded;
        public string Version;
        public string PreviewUrl;
        public uint TimeUpdated;
        public int Visibility;

        public override string ToString()
        {
            string title = String.IsNullOrWhiteSpace(Title) ? "(无标题)" : Title;
            return FormatUnixTime(TimeUpdated) + " | " + PublishedFileId + " | " + title;
        }

        private static string FormatUnixTime(uint unixTime)
        {
            if (unixTime == 0)
            {
                return "未知时间";
            }
            DateTime epoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
            return epoch.AddSeconds(unixTime).ToLocalTime().ToString("yyyy-MM-dd");
        }
    }

    internal sealed partial class SteamworksWorkshopUploader
    {
        private const string SteamUserInterfaceVersion = "SteamUser019";
        private const string SteamUtilsInterfaceVersion = "SteamUtils009";
        private const string SteamUgcInterfaceVersion = "STEAMUGC_INTERFACE_VERSION010";
        private const string SteamRemoteStorageInterfaceVersion = "STEAMREMOTESTORAGE_INTERFACE_VERSION014";
        private const uint DontStarveModToolsAppId = 245850;
        private const uint DontStarveTogetherAppId = 322330;
        private const uint DontStarveAppId = 219740;
        private const string DstModManifestFileName = "mod.manifest";
        private const string UploadStagingDirectoryName = "UploadStaging";
        private const string ActiveStagingMarkerExtension = ".active";
        private const string DontStarveRemoteStorageContentName = "mod_publish_data_file.zip";
        private const string DontStarveRemoteStoragePreviewBaseName = "mod_publish_preview";
        private const int RemoteStorageFileShareResultCallback = 1307;
        private const int RemoteStoragePublishFileResultCallback = 1309;
        private const int RemoteStorageUpdatePublishedFileResultCallback = 1315;
        private const int SteamUgcQueryCompletedCallback = 3401;
        private const int CreateItemResultCallback = 3403;
        private const int SubmitItemUpdateResultCallback = 3404;
        private const int MetadataBufferSize = 5000;
        private const ulong InvalidUpdateHandle = 0xffffffffffffffff;

        private readonly string baseDirectory;
        internal Action<ulong> ItemCreated;
        private static readonly object steamApiLock = new object();
        private static readonly TimeSpan ActiveStagingMarkerMaxAge = TimeSpan.FromHours(12);

        public SteamworksWorkshopUploader(string baseDirectory)
        {
            this.baseDirectory = Path.GetFullPath(baseDirectory);
        }

        internal static int CleanupUploadStaging(string baseDirectory, Action<string> log)
        {
            if (log == null)
            {
                log = delegate { };
            }

            string stagingRoot = GetUploadStagingRoot(baseDirectory);
            if (!Directory.Exists(stagingRoot))
            {
                return 0;
            }

            int cleaned = 0;
            foreach (string stagingFolder in Directory.GetDirectories(stagingRoot, "upload_*", SearchOption.TopDirectoryOnly))
            {
                string activeMarker = GetStagingActiveMarkerPath(stagingFolder);
                if (File.Exists(activeMarker) && !IsStaleActiveMarker(activeMarker))
                {
                    continue;
                }

                try
                {
                    Directory.Delete(stagingFolder, true);
                    DeleteStagingActiveMarker(activeMarker, log);
                    cleaned++;
                }
                catch (Exception ex)
                {
                    log("警告：清理遗留上传暂存目录失败：" + stagingFolder + "，" + ex.Message);
                }
            }

            return cleaned;
        }

        public WorkshopPublishedItem GetPublishedItem(uint appId, ulong publishedFileId, Action<string> log)
        {
            lock (steamApiLock)
            {
                return GetPublishedItemCore(appId, publishedFileId, log);
            }
        }

        private WorkshopPublishedItem GetPublishedItemCore(uint appId, ulong publishedFileId, Action<string> log)
        {
            if (publishedFileId == 0)
            {
                throw new ArgumentException("工坊 ID 不能为 0。", "publishedFileId");
            }
            if (log == null)
            {
                log = delegate { };
            }

            EnsureSteamApiDll();
            WriteSteamAppId(DontStarveModToolsAppId);

            string previousDirectory = Directory.GetCurrentDirectory();
            bool initialized = false;
            try
            {
                Directory.SetCurrentDirectory(baseDirectory);
                if (!Native.SteamAPI_IsSteamRunning())
                {
                    throw new InvalidOperationException("Steam 客户端没有运行。请先打开 Steam 并登录。");
                }

                log("初始化 Steamworks API，工具 AppID=" + DontStarveModToolsAppId + "，目标 AppID=" + appId + "，读取工坊详情 ID=" + publishedFileId + "...");
                initialized = Native.SteamAPI_Init();
                if (!initialized)
                {
                    throw new InvalidOperationException("SteamAPI_Init 失败。请确认 Steam 已登录、该 AppID 已安装或拥有权限。");
                }

                IntPtr steamClient = Native.SteamClient();
                int steamUser = Native.SteamAPI_GetHSteamUser();
                int steamPipe = Native.SteamAPI_GetHSteamPipe();
                if (steamClient == IntPtr.Zero || steamUser == 0 || steamPipe == 0)
                {
                    throw new InvalidOperationException("无法取得 Steam 客户端接口句柄。");
                }

                IntPtr steamUserInterface = GetSteamUser(steamClient, steamUser, steamPipe);
                if (steamUserInterface == IntPtr.Zero)
                {
                    throw new InvalidOperationException("无法取得 ISteamUser 接口。");
                }
                if (!Native.SteamAPI_ISteamUser_BLoggedOn(steamUserInterface))
                {
                    throw new InvalidOperationException("Steam 当前没有在线登录。请在 Steam 客户端登录后再读取详情。");
                }

                IntPtr steamUtils = GetSteamUtils(steamClient, steamPipe);
                IntPtr steamUgc = GetSteamUgc(steamClient, steamUser, steamPipe);
                if (steamUtils == IntPtr.Zero || steamUgc == IntPtr.Zero)
                {
                    throw new InvalidOperationException("无法取得 Steam UGC 查询接口。");
                }

                return QueryPublishedItemDetails(steamUtils, steamUgc, appId, publishedFileId, log);
            }
            finally
            {
                if (initialized)
                {
                    Native.SteamAPI_Shutdown();
                }
                Directory.SetCurrentDirectory(previousDirectory);
            }
        }

        private static WorkshopPublishedItem QueryPublishedItemDetails(
            IntPtr steamUtils,
            IntPtr steamUgc,
            uint appId,
            ulong publishedFileId,
            Action<string> log)
        {
            var resultById = new Dictionary<ulong, WorkshopPublishedItem>();
            ulong[] ids = new ulong[] { publishedFileId };
            WorkshopQueryLanguage[] languages = CreateWorkshopQueryLanguages();
            for (int languageIndex = 0; languageIndex < languages.Length; languageIndex++)
            {
                WorkshopQueryLanguage language = languages[languageIndex];
                ulong query = Native.SteamAPI_ISteamUGC_CreateQueryUGCDetailsRequest(steamUgc, ids, (uint)ids.Length);
                if (query == 0 || query == InvalidUpdateHandle)
                {
                    throw new InvalidOperationException("CreateQueryUGCDetailsRequest 失败。");
                }

                Native.SteamAPI_ISteamUGC_SetReturnMetadata(steamUgc, query, true);
                Native.SteamAPI_ISteamUGC_SetReturnLongDescription(steamUgc, query, true);
                TrySetAllowCachedResponse(steamUgc, query, 0, log);
                SetQueryLanguage(steamUgc, query, language, log);

                try
                {
                    ulong call = Native.SteamAPI_ISteamUGC_SendQueryUGCRequest(steamUgc, query);
                    SteamUgcQueryCompleted queryResult = WaitForCallResult<SteamUgcQueryCompleted>(
                        steamUtils,
                        call,
                        SteamUgcQueryCompletedCallback,
                        "SendQueryUGCRequest(Details)",
                        0,
                        IntPtr.Zero,
                        log);

                    if (queryResult.Result != 1)
                    {
                        throw new InvalidOperationException("查询工坊详情失败：" + ResultName(queryResult.Result));
                    }

                    int addedThisQuery = 0;
                    int updatedThisQuery = 0;
                    int skippedThisQuery = 0;
                    for (uint i = 0; i < queryResult.NumResultsReturned; i++)
                    {
                        SteamUgcDetails details;
                        if (TryGetQueryResult(steamUgc, query, i, out details) && details.PublishedFileId != 0)
                        {
                            if (details.Result != 1)
                            {
                                log("工坊详情返回非 OK，ID=" + details.PublishedFileId + "，Result=" + ResultName(details.Result) + "。");
                                skippedThisQuery++;
                                continue;
                            }

                            string queryTags = GetQueryTags(steamUgc, query, i);
                            if (details.ConsumerAppId != appId)
                            {
                                throw new InvalidOperationException("工坊物品不属于指定游戏，实际 AppID=" + details.ConsumerAppId);
                            }
                            bool added = MergePublishedItem(
                                resultById,
                                details,
                                GetQueryMetadata(steamUgc, query, i),
                                GetQueryPreviewUrl(steamUgc, query, i),
                                queryTags,
                                language);
                            if (added)
                            {
                                addedThisQuery++;
                            }
                            else
                            {
                                updatedThisQuery++;
                            }
                        }
                        else
                        {
                            skippedThisQuery++;
                        }
                    }

                    log("直接查询工坊详情 ID=" + publishedFileId
                        + " app=" + appId
                        + " language=" + language.Name
                        + " 返回 " + queryResult.NumResultsReturned
                        + "，新增 " + addedThisQuery
                        + "，更新 " + updatedThisQuery
                        + "，跳过 " + skippedThisQuery
                        + "，缓存=" + (queryResult.CachedData ? "是" : "否") + "。");
                }
                finally
                {
                    Native.SteamAPI_ISteamUGC_ReleaseQueryUGCRequest(steamUgc, query);
                }
            }

            WorkshopPublishedItem item;
            if (resultById.TryGetValue(publishedFileId, out item))
            {
                return item;
            }
            return null;
        }

        public WorkshopUploadResult Upload(WorkshopUploadItem item, Action<string> log)
        {
            lock (steamApiLock)
            {
                return UploadCore(item, log);
            }
        }

        private WorkshopUploadResult UploadCore(WorkshopUploadItem item, Action<string> log)
        {
            if (item == null)
            {
                throw new ArgumentNullException("item");
            }
            if (log == null)
            {
                log = delegate { };
            }
            if (item.AppId == DontStarveAppId)
            {
                return UploadDontStarveRemoteStorageCore(item, log);
            }

            string previousDirectory = Directory.GetCurrentDirectory();
            bool initialized = false;
            string stagedContentFolder = null;
            string contentFolderForUpload = item.ContentFolder;
            try
            {
                if (item.UpdateContent)
                {
                    stagedContentFolder = CreateStagedContentFolder(item.ContentFolder, item.UploadRedundantFiles, item.AppId == DontStarveTogetherAppId, log);
                    contentFolderForUpload = stagedContentFolder;
                }

                EnsureSteamApiDll();
                WriteSteamAppId(DontStarveModToolsAppId);

                Directory.SetCurrentDirectory(baseDirectory);
                if (!Native.SteamAPI_IsSteamRunning())
                {
                    throw new InvalidOperationException("Steam 客户端没有运行。请先打开 Steam 并登录。");
                }

                log("初始化 Steamworks API，工具 AppID=" + DontStarveModToolsAppId + "，目标 AppID=" + item.AppId + "...");
                initialized = Native.SteamAPI_Init();
                if (!initialized)
                {
                    throw new InvalidOperationException("SteamAPI_Init 失败。请确认 Steam 已登录、该 AppID 已安装或拥有权限，并关闭同目录下可能占用 steam_appid.txt 的旧进程。");
                }

                IntPtr steamClient = Native.SteamClient();
                int steamUser = Native.SteamAPI_GetHSteamUser();
                int steamPipe = Native.SteamAPI_GetHSteamPipe();
                if (steamClient == IntPtr.Zero || steamUser == 0 || steamPipe == 0)
                {
                    throw new InvalidOperationException("无法取得 Steam 客户端接口句柄。");
                }

                IntPtr steamUserInterface = GetSteamUser(steamClient, steamUser, steamPipe);
                if (steamUserInterface != IntPtr.Zero && !Native.SteamAPI_ISteamUser_BLoggedOn(steamUserInterface))
                {
                    throw new InvalidOperationException("Steam 当前没有在线登录。请在 Steam 客户端登录后再上传。");
                }

                IntPtr steamUtils = GetSteamUtils(steamClient, steamPipe);
                IntPtr steamUgc = GetSteamUgc(steamClient, steamUser, steamPipe);
                if (steamUtils == IntPtr.Zero)
                {
                    throw new InvalidOperationException("无法取得 ISteamUtils 接口。");
                }
                if (steamUgc == IntPtr.Zero)
                {
                    throw new InvalidOperationException("无法取得 ISteamUGC 接口；当前 steam_api.dll 可能和工具不兼容。");
                }

                ulong publishedFileId = item.PublishedFileId;
                bool needsLegalAgreement = false;
                if (publishedFileId == 0)
                {
                    log("正在创建新的创意工坊物品...");
                    ulong createCall = Native.SteamAPI_ISteamUGC_CreateItem(steamUgc, item.AppId, 0);
                    CreateItemResult createResult = WaitForCallResult<CreateItemResult>(
                        steamUtils,
                        createCall,
                        CreateItemResultCallback,
                        "CreateItem",
                        0,
                        steamUgc,
                        log);

                    if (createResult.Result != 1)
                    {
                        throw new InvalidOperationException("CreateItem 失败：" + ResultName(createResult.Result));
                    }
                    publishedFileId = createResult.PublishedFileId;
                    ItemCreated?.Invoke(publishedFileId);
                    needsLegalAgreement = createResult.UserNeedsToAcceptWorkshopLegalAgreement;
                    log("已创建工坊物品，ID=" + publishedFileId);
                }
                else
                {
                    log("正在更新已有工坊物品，ID=" + publishedFileId);
                }

                ulong updateHandle = Native.SteamAPI_ISteamUGC_StartItemUpdate(steamUgc, item.AppId, publishedFileId);
                if (updateHandle == 0 || updateHandle == InvalidUpdateHandle)
                {
                    throw new InvalidOperationException("StartItemUpdate 失败，可能没有权限更新这个工坊物品。");
                }

                if (item.UpdateMetadata)
                {
                    log("更新标题和简介...");
                    Require(NativeSetString(delegate(IntPtr p) { return Native.SteamAPI_ISteamUGC_SetItemTitle(steamUgc, updateHandle, p); }, item.Title), "SetItemTitle");
                    Require(NativeSetString(delegate(IntPtr p) { return Native.SteamAPI_ISteamUGC_SetItemDescription(steamUgc, updateHandle, p); }, item.Description), "SetItemDescription");
                }

                if (item.UpdateMetadata || item.UpdateTags)
                {
                    string[] tags = item.Tags ?? new string[0];
                    log("更新 Tags：" + (tags.Length == 0 ? "(未选择)" : String.Join(", ", tags)));
                    Require(NativeSetTags(steamUgc, updateHandle, tags), "SetItemTags");
                    log("Tags 更新请求已写入 Steam UGC 更新句柄。");
                }

                if (item.AppId == DontStarveAppId)
                {
                    if (item.UpdateMetadata || item.UpdateVersionMetadata)
                    {
                        log("单机版跳过版本 metadata。");
                    }
                }
                else if (item.UpdateMetadata || item.UpdateVersionMetadata)
                {
                    string metadata = BuildWorkshopMetadata(item.Version, item.VersionCompatible);
                    if (!String.IsNullOrWhiteSpace(metadata))
                    {
                        log("更新版本 metadata：" + item.Version);
                        Require(NativeSetString(delegate(IntPtr p) { return Native.SteamAPI_ISteamUGC_SetItemMetadata(steamUgc, updateHandle, p); }, metadata), "SetItemMetadata");
                    }
                }

                if (item.UpdateContent)
                {
                    log("更新模组文件...");
                    Require(NativeSetString(delegate(IntPtr p) { return Native.SteamAPI_ISteamUGC_SetItemContent(steamUgc, updateHandle, p); }, contentFolderForUpload), "SetItemContent");
                }

                if (item.UpdatePreview)
                {
                    log("更新预览图...");
                    Require(NativeSetString(delegate(IntPtr p) { return Native.SteamAPI_ISteamUGC_SetItemPreview(steamUgc, updateHandle, p); }, item.PreviewFile), "SetItemPreview");
                }

                Require(Native.SteamAPI_ISteamUGC_SetItemVisibility(steamUgc, updateHandle, item.Visibility), "SetItemVisibility");

                string submitChangeNote = item.AppId == DontStarveAppId ? "" : (item.ChangeNote ?? "");
                if (item.AppId == DontStarveAppId && !String.IsNullOrWhiteSpace(item.ChangeNote))
                {
                    log("单机版上传忽略更新说明。");
                }

                log("正在提交更新...");
                ulong submitCall = NativeSetStringOrNull(
                    delegate(IntPtr p) { return Native.SteamAPI_ISteamUGC_SubmitItemUpdate(steamUgc, updateHandle, p); },
                    submitChangeNote);

                SubmitItemUpdateResult submitResult = WaitForCallResult<SubmitItemUpdateResult>(
                    steamUtils,
                    submitCall,
                    SubmitItemUpdateResultCallback,
                    "SubmitItemUpdate",
                    updateHandle,
                    steamUgc,
                    log);
				log("提交更新结果" + submitResult.Result);
                if (submitResult.Result != 1)
                {
                    throw new InvalidOperationException("SubmitItemUpdate 失败：" + ResultName(submitResult.Result));
                }

                log("SubmitItemUpdate 返回 OK，PublishedFileId=" + submitResult.PublishedFileId
                    + "，需要接受协议=" + (submitResult.UserNeedsToAcceptWorkshopLegalAgreement ? "是" : "否") + "。");
                needsLegalAgreement = needsLegalAgreement || submitResult.UserNeedsToAcceptWorkshopLegalAgreement;
                if (submitResult.PublishedFileId != 0)
                {
                    publishedFileId = submitResult.PublishedFileId;
                }

                return new WorkshopUploadResult
                {
                    PublishedFileId = publishedFileId,
                    UserNeedsToAcceptWorkshopLegalAgreement = needsLegalAgreement
                };
            }
            finally
            {
                if (initialized)
                {
                    Native.SteamAPI_Shutdown();
                }
                Directory.SetCurrentDirectory(previousDirectory);
                DeleteStagedContentFolder(stagedContentFolder, log);
            }
        }

        private WorkshopUploadResult UploadDontStarveRemoteStorageCore(WorkshopUploadItem item, Action<string> log)
        {
            string previousDirectory = Directory.GetCurrentDirectory();
            bool initialized = false;
            string stagedContentFolder = null;
            string packageFile = null;
            try
            {
                if (item.UpdateContent)
                {
                    stagedContentFolder = CreateStagedContentFolder(item.ContentFolder, item.UploadRedundantFiles, false, log);
                    packageFile = CreateDontStarveRemoteStoragePackage(stagedContentFolder, log);
                }

                EnsureSteamApiDll();
                WriteSteamAppId(DontStarveModToolsAppId);

                Directory.SetCurrentDirectory(baseDirectory);
                if (!Native.SteamAPI_IsSteamRunning())
                {
                    throw new InvalidOperationException("Steam 客户端没有运行。请先打开 Steam 并登录。");
                }

                log("初始化 Steamworks API，工具 AppID=" + DontStarveModToolsAppId + "，目标 AppID=" + item.AppId + "，单机版使用 RemoteStorage 旧工坊接口...");
                initialized = Native.SteamAPI_Init();
                if (!initialized)
                {
                    throw new InvalidOperationException("SteamAPI_Init 失败。请确认 Steam 已登录、Don't Starve Mod Tools 已安装，并关闭同目录下可能占用 steam_appid.txt 的旧进程。");
                }

                IntPtr steamClient = Native.SteamClient();
                int steamUser = Native.SteamAPI_GetHSteamUser();
                int steamPipe = Native.SteamAPI_GetHSteamPipe();
                if (steamClient == IntPtr.Zero || steamUser == 0 || steamPipe == 0)
                {
                    throw new InvalidOperationException("无法取得 Steam 客户端接口句柄。");
                }

                IntPtr steamUserInterface = GetSteamUser(steamClient, steamUser, steamPipe);
                if (steamUserInterface != IntPtr.Zero && !Native.SteamAPI_ISteamUser_BLoggedOn(steamUserInterface))
                {
                    throw new InvalidOperationException("Steam 当前没有在线登录。请在 Steam 客户端登录后再上传。");
                }

                IntPtr steamUtils = GetSteamUtils(steamClient, steamPipe);
                IntPtr steamRemoteStorage = GetSteamRemoteStorage(steamClient, steamUser, steamPipe);
                if (steamUtils == IntPtr.Zero)
                {
                    throw new InvalidOperationException("无法取得 ISteamUtils 接口。");
                }
                if (steamRemoteStorage == IntPtr.Zero)
                {
                    throw new InvalidOperationException("无法取得 ISteamRemoteStorage 接口；当前 steam_api.dll 可能和工具不兼容。");
                }

                string remoteContentName = DontStarveRemoteStorageContentName;
                string remotePreviewName = BuildDontStarveRemotePreviewName(item.PreviewFile);
                if (item.PublishedFileId == 0)
                {
                    if (String.IsNullOrWhiteSpace(packageFile) || !File.Exists(packageFile))
                    {
                        throw new InvalidOperationException("创建单机版工坊物品时必须上传模组文件。");
                    }
                    if (String.IsNullOrWhiteSpace(item.PreviewFile) || !File.Exists(item.PreviewFile))
                    {
                        throw new InvalidOperationException("创建单机版工坊物品时必须上传预览图。");
                    }

                    remoteContentName = RemoteStorageWriteAndShareFile(steamUtils, steamRemoteStorage, remoteContentName, packageFile, "单机版模组包", log);
                    remotePreviewName = RemoteStorageWriteAndShareFile(steamUtils, steamRemoteStorage, remotePreviewName, item.PreviewFile, "单机版预览图", log);

                    log("正在创建新的单机版工坊物品...");
                    RemoteStoragePublishFileResult publishResult = RemoteStoragePublishWorkshopFile(
                        steamUtils,
                        steamRemoteStorage,
                        remoteContentName,
                        remotePreviewName,
                        item,
                        log);
                    if (publishResult.Result != 1)
                    {
                        throw new InvalidOperationException("PublishWorkshopFile 失败：" + ResultName(publishResult.Result));
                    }

                    log("单机版工坊物品创建成功，ID=" + publishResult.PublishedFileId);
                    ItemCreated?.Invoke(publishResult.PublishedFileId);
                    return new WorkshopUploadResult
                    {
                        PublishedFileId = publishResult.PublishedFileId,
                        UserNeedsToAcceptWorkshopLegalAgreement = publishResult.UserNeedsToAcceptWorkshopLegalAgreement
                    };
                }

                log("正在更新已有单机版工坊物品，ID=" + item.PublishedFileId);
                ulong updateHandle = Native.SteamAPI_ISteamRemoteStorage_CreatePublishedFileUpdateRequest(steamRemoteStorage, item.PublishedFileId);
                if (updateHandle == 0 || updateHandle == InvalidUpdateHandle)
                {
                    throw new InvalidOperationException("CreatePublishedFileUpdateRequest 失败，可能没有权限更新这个工坊物品。");
                }

                if (item.UpdateContent)
                {
                    remoteContentName = RemoteStorageWriteAndShareFile(steamUtils, steamRemoteStorage, remoteContentName, packageFile, "单机版模组包", log);
                    log("更新单机版模组包...");
                    Require(NativeSetString(delegate(IntPtr p)
                    {
                        return Native.SteamAPI_ISteamRemoteStorage_UpdatePublishedFileFile(steamRemoteStorage, updateHandle, p);
                    }, remoteContentName), "UpdatePublishedFileFile");
                }

                if (item.UpdatePreview)
                {
                    if (String.IsNullOrWhiteSpace(item.PreviewFile) || !File.Exists(item.PreviewFile))
                    {
                        throw new InvalidOperationException("已勾选更新预览图，但预览图不存在。");
                    }
                    remotePreviewName = RemoteStorageWriteAndShareFile(steamUtils, steamRemoteStorage, remotePreviewName, item.PreviewFile, "单机版预览图", log);
                    log("更新单机版预览图...");
                    Require(NativeSetString(delegate(IntPtr p)
                    {
                        return Native.SteamAPI_ISteamRemoteStorage_UpdatePublishedFilePreviewFile(steamRemoteStorage, updateHandle, p);
                    }, remotePreviewName), "UpdatePublishedFilePreviewFile");
                }

                if (item.UpdateMetadata)
                {
                    log("更新标题和简介...");
                    Require(NativeSetString(delegate(IntPtr p)
                    {
                        return Native.SteamAPI_ISteamRemoteStorage_UpdatePublishedFileTitle(steamRemoteStorage, updateHandle, p);
                    }, item.Title), "UpdatePublishedFileTitle");
                    Require(NativeSetString(delegate(IntPtr p)
                    {
                        return Native.SteamAPI_ISteamRemoteStorage_UpdatePublishedFileDescription(steamRemoteStorage, updateHandle, p);
                    }, item.Description), "UpdatePublishedFileDescription");
                }

                if (item.UpdateMetadata || item.UpdateTags)
                {
                    string[] tags = item.Tags ?? new string[0];
                    log("更新 Tags：" + (tags.Length == 0 ? "(未选择)" : String.Join(", ", tags)));
                    Require(RemoteStorageUpdatePublishedFileTags(steamRemoteStorage, updateHandle, tags), "UpdatePublishedFileTags");
                    log("Tags 更新请求已写入 RemoteStorage 更新句柄。");
                }

                Require(Native.SteamAPI_ISteamRemoteStorage_UpdatePublishedFileVisibility(steamRemoteStorage, updateHandle, item.Visibility), "UpdatePublishedFileVisibility");
                log("单机版上传忽略更新说明。");
                log("正在提交单机版工坊更新...");
                ulong commitCall = Native.SteamAPI_ISteamRemoteStorage_CommitPublishedFileUpdate(steamRemoteStorage, updateHandle);
                RemoteStorageUpdatePublishedFileResult updateResult;
                try
                {
                    updateResult = WaitForCallResult<RemoteStorageUpdatePublishedFileResult>(
                        steamUtils,
                        commitCall,
                        RemoteStorageUpdatePublishedFileResultCallback,
                        "CommitPublishedFileUpdate",
                        0,
                        IntPtr.Zero,
                        log);
                }
                catch (InvalidOperationException ex)
                {
                    if (IsCallbackReadFailure(ex, "CommitPublishedFileUpdate") || IsSteamCallMarkedFailed(ex, "CommitPublishedFileUpdate"))
                    {
                        log("CommitPublishedFileUpdate 回调状态异常，更新请求可能已经提交；继续执行二次检查确认结果。原始信息：" + ex.Message);
                        return new WorkshopUploadResult
                        {
                            PublishedFileId = item.PublishedFileId,
                            UserNeedsToAcceptWorkshopLegalAgreement = false,
                            SubmissionUncertain = true
                        };
                    }
                    throw;
                }

                if (updateResult.Result != 1)
                {
                    throw new InvalidOperationException("CommitPublishedFileUpdate 失败：" + ResultName(updateResult.Result));
                }

                return new WorkshopUploadResult
                {
                    PublishedFileId = updateResult.PublishedFileId == 0 ? item.PublishedFileId : updateResult.PublishedFileId,
                    UserNeedsToAcceptWorkshopLegalAgreement = updateResult.UserNeedsToAcceptWorkshopLegalAgreement
                };
            }
            finally
            {
                if (initialized)
                {
                    Native.SteamAPI_Shutdown();
                }
                Directory.SetCurrentDirectory(previousDirectory);
                DeleteStagedContentFolder(stagedContentFolder, log);
                DeleteTempFile(packageFile, log);
            }
        }

        private string CreateDontStarveRemoteStoragePackage(string stagedContentFolder, Action<string> log)
        {
            if (String.IsNullOrWhiteSpace(stagedContentFolder) || !Directory.Exists(stagedContentFolder))
            {
                throw new DirectoryNotFoundException("上传暂存目录不存在：" + stagedContentFolder);
            }

            string packageFile = Path.Combine(Path.GetDirectoryName(stagedContentFolder), "mod_publish_data_file_" + Guid.NewGuid().ToString("N") + ".zip");
            int fileCount = 0;
            using (FileStream stream = File.Open(packageFile, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None))
            using (ZipArchive archive = new ZipArchive(stream, ZipArchiveMode.Create))
            {
                foreach (string file in Directory.GetFiles(stagedContentFolder, "*", SearchOption.AllDirectories))
                {
                    string entryName = GetRelativeZipPath(stagedContentFolder, file);
                    archive.CreateEntryFromFile(file, entryName, CompressionLevel.Optimal);
                    fileCount++;
                }
            }

            long bytes = new FileInfo(packageFile).Length;
            log("已生成单机版上传包：" + fileCount + " 个文件，" + bytes + " bytes。");
            return packageFile;
        }

        private static string GetRelativeZipPath(string root, string file)
        {
            string fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
            string fullFile = Path.GetFullPath(file);
            string relative = fullFile.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase) ? fullFile.Substring(fullRoot.Length) : Path.GetFileName(file);
            return relative.Replace(Path.DirectorySeparatorChar, '/').Replace(Path.AltDirectorySeparatorChar, '/');
        }

        private static string BuildDontStarveRemotePreviewName(string previewFile)
        {
            string extension = Path.GetExtension(previewFile ?? "").ToLowerInvariant();
            if (extension == ".jpg" || extension == ".jpeg")
            {
                return DontStarveRemoteStoragePreviewBaseName + ".jpg";
            }
            if (extension == ".gif")
            {
                return DontStarveRemoteStoragePreviewBaseName + ".gif";
            }
            return DontStarveRemoteStoragePreviewBaseName + ".png";
        }

        private static string RemoteStorageWriteAndShareFile(IntPtr steamUtils, IntPtr steamRemoteStorage, string remoteName, string localPath, string label, Action<string> log)
        {
            if (String.IsNullOrWhiteSpace(localPath) || !File.Exists(localPath))
            {
                throw new FileNotFoundException(label + "不存在。", localPath);
            }

            byte[] data = File.ReadAllBytes(localPath);
            string fallbackName = BuildUniqueRemoteStorageName(remoteName);
            InvalidOperationException firstError = null;
            try
            {
                RemoteStorageWriteAndShareFileOnce(steamUtils, steamRemoteStorage, remoteName, data, label, log);
                return remoteName;
            }
            catch (InvalidOperationException ex)
            {
                firstError = ex;
                if (!IsRemoteStorageShareFileNotFound(ex, remoteName))
                {
                    throw;
                }
                log("警告：" + ex.Message + "；改用唯一 Steam Cloud 文件名重试。");
            }

            try
            {
                RemoteStorageWriteAndShareFileOnce(steamUtils, steamRemoteStorage, fallbackName, data, label, log);
                return fallbackName;
            }
            catch (InvalidOperationException ex)
            {
                throw new InvalidOperationException("共享 " + label + " 失败。固定文件名和唯一文件名都不可用。首次错误：" + firstError.Message + "；重试错误：" + ex.Message);
            }
        }

        private static void RemoteStorageWriteAndShareFileOnce(IntPtr steamUtils, IntPtr steamRemoteStorage, string remoteName, byte[] data, string label, Action<string> log)
        {
            log("写入 Steam Cloud：" + label + " -> " + remoteName + " (" + data.Length + " bytes)");
            NativeSetString(delegate(IntPtr p)
            {
                return Native.SteamAPI_ISteamRemoteStorage_FileDelete(steamRemoteStorage, p);
            }, remoteName);

            bool writeOk = NativeSetString(delegate(IntPtr p)
            {
                return Native.SteamAPI_ISteamRemoteStorage_FileWrite(steamRemoteStorage, p, data, data.Length);
            }, remoteName);
            Require(writeOk, "FileWrite(" + remoteName + ")");

            bool exists = NativeSetString(delegate(IntPtr p)
            {
                return Native.SteamAPI_ISteamRemoteStorage_FileExists(steamRemoteStorage, p);
            }, remoteName);
            int steamSize = NativeGetRemoteStorageFileSize(steamRemoteStorage, remoteName);
            if (!exists || steamSize < 0)
            {
                throw new InvalidOperationException("FileWrite(" + remoteName + ") 返回成功，但 Steam Cloud 随后不可见该文件。");
            }
            if (steamSize != data.Length)
            {
                log("警告：Steam Cloud 文件大小和本地不一致：" + steamSize + " != " + data.Length + "。");
            }

            log("共享 Steam Cloud 文件：" + remoteName);
            ulong shareCall = NativeSetString(delegate(IntPtr p)
            {
                return Native.SteamAPI_ISteamRemoteStorage_FileShare(steamRemoteStorage, p);
            }, remoteName);
            RemoteStorageFileShareResult shareResult = WaitForCallResult<RemoteStorageFileShareResult>(
                steamUtils,
                shareCall,
                RemoteStorageFileShareResultCallback,
                "FileShare",
                0,
                IntPtr.Zero,
                log);
            if (shareResult.Result != 1)
            {
                throw new InvalidOperationException("FileShare(" + remoteName + ") 失败：" + ResultName(shareResult.Result));
            }
        }

        private static int NativeGetRemoteStorageFileSize(IntPtr steamRemoteStorage, string remoteName)
        {
            IntPtr ptr = StringToUtf8(remoteName ?? "");
            try
            {
                return Native.SteamAPI_ISteamRemoteStorage_GetFileSize(steamRemoteStorage, ptr);
            }
            finally
            {
                Marshal.FreeHGlobal(ptr);
            }
        }

        private static string BuildUniqueRemoteStorageName(string preferredName)
        {
            string extension = Path.GetExtension(preferredName ?? "");
            string name = Path.GetFileNameWithoutExtension(preferredName ?? "");
            if (String.IsNullOrWhiteSpace(name))
            {
                name = "mod_publish_data_file";
            }
            if (String.IsNullOrWhiteSpace(extension))
            {
                extension = ".dat";
            }
            return name + "_" + DateTime.UtcNow.ToString("yyyyMMddHHmmss") + "_" + Guid.NewGuid().ToString("N").Substring(0, 8) + extension;
        }

        private static bool IsRemoteStorageShareFileNotFound(Exception ex, string remoteName)
        {
            string message = ex == null ? "" : (ex.Message ?? "");
            return message.IndexOf("FileShare(" + remoteName + ")", StringComparison.OrdinalIgnoreCase) >= 0
                && message.IndexOf("FileNotFound", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static RemoteStoragePublishFileResult RemoteStoragePublishWorkshopFile(
            IntPtr steamUtils,
            IntPtr steamRemoteStorage,
            string remoteContentName,
            string remotePreviewName,
            WorkshopUploadItem item,
            Action<string> log)
        {
            string[] tags = item.Tags ?? new string[0];
            log("发布单机版 Tags：" + (tags.Length == 0 ? "(未选择)" : String.Join(", ", tags)));
            RemoteStoragePublishFileResult result = WithSteamTags(tags, delegate(ref SteamParamStringArray tagArray)
            {
                return RemoteStoragePublishWorkshopFileWithTags(
                    steamUtils,
                    steamRemoteStorage,
                    remoteContentName,
                    remotePreviewName,
                    item,
                    ref tagArray,
                    log);
            });
            return result;
        }

        private static RemoteStoragePublishFileResult RemoteStoragePublishWorkshopFileWithTags(
            IntPtr steamUtils,
            IntPtr steamRemoteStorage,
            string remoteContentName,
            string remotePreviewName,
            WorkshopUploadItem item,
            ref SteamParamStringArray tagArray,
            Action<string> log)
        {
            IntPtr contentPtr = StringToUtf8(remoteContentName);
            IntPtr previewPtr = StringToUtf8(remotePreviewName);
            IntPtr titlePtr = StringToUtf8(item.Title ?? "");
            IntPtr descriptionPtr = StringToUtf8(item.Description ?? "");
            try
            {
                ulong publishCall = Native.SteamAPI_ISteamRemoteStorage_PublishWorkshopFile(
                    steamRemoteStorage,
                    contentPtr,
                    previewPtr,
                    item.AppId,
                    titlePtr,
                    descriptionPtr,
                    item.Visibility,
                    ref tagArray,
                    0);
                return WaitForCallResult<RemoteStoragePublishFileResult>(
                    steamUtils,
                    publishCall,
                    RemoteStoragePublishFileResultCallback,
                    "PublishWorkshopFile",
                    0,
                    IntPtr.Zero,
                    log);
            }
            finally
            {
                Marshal.FreeHGlobal(contentPtr);
                Marshal.FreeHGlobal(previewPtr);
                Marshal.FreeHGlobal(titlePtr);
                Marshal.FreeHGlobal(descriptionPtr);
            }
        }

        private static bool RemoteStorageUpdatePublishedFileTags(IntPtr steamRemoteStorage, ulong updateHandle, string[] tags)
        {
            return WithSteamTags(tags, delegate(ref SteamParamStringArray tagArray)
            {
                return Native.SteamAPI_ISteamRemoteStorage_UpdatePublishedFileTags(steamRemoteStorage, updateHandle, ref tagArray);
            });
        }

        private string CreateStagedContentFolder(string sourceFolder, bool uploadRedundantFiles, bool generateDstModManifest, Action<string> log)
        {
            if (String.IsNullOrWhiteSpace(sourceFolder) || !Directory.Exists(sourceFolder))
            {
                throw new DirectoryNotFoundException("模组目录不存在：" + sourceFolder);
            }

            string sourceRoot = Path.GetFullPath(sourceFolder);
            string stagingRoot = GetUploadStagingRoot(baseDirectory);
            Directory.CreateDirectory(stagingRoot);

            string stagingFolder = Path.Combine(stagingRoot, "upload_" + DateTime.UtcNow.ToString("yyyyMMddHHmmss") + "_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(stagingFolder);
            WriteStagingActiveMarker(stagingFolder);

            var stats = new StagedContentStats();
            CopyStagedDirectory(sourceRoot, sourceRoot, stagingFolder, uploadRedundantFiles, generateDstModManifest, stats);
            if (generateDstModManifest)
            {
                int manifestFileCount = WriteDstModManifest(stagingFolder);
                log("已生成联机版 mod.manifest：记录 " + manifestFileCount + " 个文件。");
            }

            log("已生成上传暂存目录：复制 " + stats.CopiedFiles + " 个文件，跳过 " + stats.SkippedFiles + " 个文件、" + stats.SkippedDirectories + " 个目录。冗余文件=" + (uploadRedundantFiles ? "上传" : "过滤") + "。");
            return stagingFolder;
        }

        internal static int WriteDstModManifest(string stagingFolder)
        {
            List<string> manifestPaths = CollectDstModManifestPaths(stagingFolder);
            string manifestFile = Path.Combine(stagingFolder, DstModManifestFileName);

            using (FileStream stream = File.Open(manifestFile, FileMode.Create, FileAccess.Write, FileShare.None))
            using (var writer = new BinaryWriter(stream))
            {
                writer.Write(Encoding.ASCII.GetBytes("MNFS"));
                writer.Write((uint)1);
                writer.Write((uint)manifestPaths.Count);

                foreach (string manifestPath in manifestPaths)
                {
                    writer.Write(ComputeSdbmHash(manifestPath));
                }
            }

            return manifestPaths.Count;
        }

        private static List<string> CollectDstModManifestPaths(string stagingFolder)
        {
            var paths = new List<string>();
            CollectDstModManifestPaths(stagingFolder, stagingFolder, paths);
            return paths;
        }

        private static void CollectDstModManifestPaths(string stagingRoot, string currentDirectory, List<string> paths)
        {
            string[] files = Directory.GetFiles(currentDirectory);
            Array.Sort(files, StringComparer.OrdinalIgnoreCase);
            foreach (string file in files)
            {
                string relativePath = GetRelativeZipPath(stagingRoot, file);
                if (String.Equals(relativePath, DstModManifestFileName, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                paths.Add(relativePath.ToLowerInvariant());
            }

            string[] directories = Directory.GetDirectories(currentDirectory);
            Array.Sort(directories, StringComparer.OrdinalIgnoreCase);
            foreach (string directory in directories)
            {
                var info = new DirectoryInfo(directory);
                if ((info.Attributes & FileAttributes.ReparsePoint) == FileAttributes.ReparsePoint)
                {
                    continue;
                }

                CollectDstModManifestPaths(stagingRoot, directory, paths);
            }
        }

        private static uint ComputeSdbmHash(string value)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(value ?? "");
            uint hash = 0;
            unchecked
            {
                for (int i = 0; i < bytes.Length; i++)
                {
                    hash = (uint)bytes[i] + (hash << 6) + (hash << 16) - hash;
                }
            }

            return hash;
        }

        private static void CopyStagedDirectory(string sourceRoot, string sourceDirectory, string targetDirectory, bool uploadRedundantFiles, bool generateDstModManifest, StagedContentStats stats)
        {
            Directory.CreateDirectory(targetDirectory);

            foreach (string directory in Directory.GetDirectories(sourceDirectory))
            {
                var info = new DirectoryInfo(directory);
                if (ShouldSkipUploadDirectory(info))
                {
                    stats.SkippedDirectories++;
                    continue;
                }

                string targetChild = Path.Combine(targetDirectory, info.Name);
                CopyStagedDirectory(sourceRoot, info.FullName, targetChild, uploadRedundantFiles, generateDstModManifest, stats);
            }

            foreach (string file in Directory.GetFiles(sourceDirectory))
            {
                var info = new FileInfo(file);
                if (ShouldSkipUploadFile(info, uploadRedundantFiles, sourceRoot, generateDstModManifest))
                {
                    stats.SkippedFiles++;
                    continue;
                }

                string targetFile = Path.Combine(targetDirectory, info.Name);
                File.Copy(info.FullName, targetFile, true);
                File.SetLastWriteTimeUtc(targetFile, info.LastWriteTimeUtc);
                stats.CopiedFiles++;
            }
        }

        internal static bool ShouldSkipUploadDirectory(DirectoryInfo directory)
        {
            if (directory == null)
            {
                return true;
            }

            string name = directory.Name;
            if (String.IsNullOrWhiteSpace(name) || name.StartsWith(".", StringComparison.Ordinal))
            {
                return true;
            }
            if ((directory.Attributes & FileAttributes.ReparsePoint) == FileAttributes.ReparsePoint)
            {
                return true;
            }

            return false;
        }

        internal static bool ShouldSkipUploadFile(FileInfo file, bool uploadRedundantFiles, string sourceRoot, bool generateDstModManifest)
        {
            if (file == null)
            {
                return true;
            }

            string name = file.Name;
            if (String.IsNullOrWhiteSpace(name) || name.StartsWith(".", StringComparison.Ordinal))
            {
                return true;
            }
            if (generateDstModManifest && IsRootModManifest(file, sourceRoot))
            {
                return true;
            }
            if ((file.Attributes & FileAttributes.ReparsePoint) == FileAttributes.ReparsePoint)
            {
                return true;
            }

            if (IsIllegalUploadExtension(file.Extension))
            {
                return true;
            }

            return !uploadRedundantFiles && IsRedundantUploadFile(file.Extension);
        }

        private static bool IsRootModManifest(FileInfo file, string sourceRoot)
        {
            if (file == null || String.IsNullOrWhiteSpace(sourceRoot))
            {
                return false;
            }

            string name = file.Name;
            if (!String.Equals(name, DstModManifestFileName, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            try
            {
                string expectedPath = Path.GetFullPath(Path.Combine(sourceRoot, DstModManifestFileName));
                string actualPath = Path.GetFullPath(file.FullName);
                return String.Equals(actualPath, expectedPath, StringComparison.OrdinalIgnoreCase);
            }
            catch
            {
                return false;
            }
        }

        private static bool IsIllegalUploadExtension(string extension)
        {
            // 官方 ModUploader 的非法格式表只有此占位项，不限制 DLL、EXE 或脚本。
            return String.Equals(extension, ".illegaldummyformat", StringComparison.Ordinal);
        }

        private static bool IsRedundantUploadFile(string extension)
        {
            // 与官方的九项冗余格式及区分大小写的比较保持一致，ZIP 等其他格式正常上传。
            switch (extension)
            {
                case ".png":
                case ".jpg":
                case ".jpeg":
                case ".gif":
                case ".bmp":
                case ".fla":
                case ".scml":
                case ".mp3":
                case ".wav":
                    return true;
                default:
                    return false;
            }
        }

        private static string GetUploadStagingRoot(string baseDirectory)
        {
            return Path.Combine(Path.GetFullPath(baseDirectory), "UploaderData", UploadStagingDirectoryName);
        }

        private static string GetStagingActiveMarkerPath(string stagingFolder)
        {
            string parent = Path.GetDirectoryName(stagingFolder);
            string name = Path.GetFileName(stagingFolder);
            return Path.Combine(parent, name + ActiveStagingMarkerExtension);
        }

        private static bool IsStaleActiveMarker(string activeMarker)
        {
            try
            {
                return DateTime.UtcNow - File.GetLastWriteTimeUtc(activeMarker) >= ActiveStagingMarkerMaxAge;
            }
            catch
            {
                return true;
            }
        }

        private static void WriteStagingActiveMarker(string stagingFolder)
        {
            string activeMarker = GetStagingActiveMarkerPath(stagingFolder);
            string markerText = DateTime.UtcNow.ToString("o") + Environment.NewLine + stagingFolder;
            File.WriteAllText(activeMarker, markerText, Encoding.UTF8);
        }

        private static void DeleteStagingActiveMarker(string activeMarker, Action<string> log)
        {
            if (String.IsNullOrWhiteSpace(activeMarker) || !File.Exists(activeMarker))
            {
                return;
            }

            try
            {
                File.Delete(activeMarker);
            }
            catch (Exception ex)
            {
                if (log != null)
                {
                    log("警告：清理上传暂存 active 标记失败：" + ex.Message);
                }
            }
        }

        private static void DeleteStagedContentFolder(string stagedContentFolder, Action<string> log)
        {
            if (String.IsNullOrWhiteSpace(stagedContentFolder) || !Directory.Exists(stagedContentFolder))
            {
                if (!String.IsNullOrWhiteSpace(stagedContentFolder))
                {
                    DeleteStagingActiveMarker(GetStagingActiveMarkerPath(stagedContentFolder), log);
                }
                return;
            }

            try
            {
                Directory.Delete(stagedContentFolder, true);
            }
            catch (Exception ex)
            {
                if (log != null)
                {
                    log("警告：清理上传暂存目录失败：" + ex.Message);
                }
            }
            finally
            {
                DeleteStagingActiveMarker(GetStagingActiveMarkerPath(stagedContentFolder), log);
            }
        }

        private static void DeleteTempFile(string path, Action<string> log)
        {
            if (String.IsNullOrWhiteSpace(path) || !File.Exists(path))
            {
                return;
            }

            try
            {
                File.Delete(path);
            }
            catch (Exception ex)
            {
                if (log != null)
                {
                    log("警告：清理上传临时文件失败：" + ex.Message);
                }
            }
        }

        private void EnsureSteamApiDll()
        {
            string target = Path.Combine(baseDirectory, "steam_api.dll");
            if (File.Exists(target))
            {
                return;
            }

            string source = Path.Combine(Directory.GetParent(baseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)).FullName, "steam_api.dll");
            if (!File.Exists(source))
            {
                throw new FileNotFoundException("没有找到 steam_api.dll。请确认工具位于 Don't Starve Mod Tools 目录下。", source);
            }

            File.Copy(source, target, false);
        }

        private void WriteSteamAppId(uint appId)
        {
            string appIdPath = Path.Combine(baseDirectory, "steam_appid.txt");
            File.WriteAllText(appIdPath, appId.ToString(), Encoding.ASCII);
        }

        private static IntPtr GetSteamUser(IntPtr steamClient, int steamUser, int steamPipe)
        {
            return Native.SteamAPI_ISteamClient_GetISteamUser(steamClient, steamUser, steamPipe, SteamUserInterfaceVersion);
        }

        private static IntPtr GetSteamUtils(IntPtr steamClient, int steamPipe)
        {
            return Native.SteamAPI_ISteamClient_GetISteamUtils(steamClient, steamPipe, SteamUtilsInterfaceVersion);
        }

        private static IntPtr GetSteamUgc(IntPtr steamClient, int steamUser, int steamPipe)
        {
            return Native.SteamAPI_ISteamClient_GetISteamUGC(steamClient, steamUser, steamPipe, SteamUgcInterfaceVersion);
        }

        private static IntPtr GetSteamRemoteStorage(IntPtr steamClient, int steamUser, int steamPipe)
        {
            return Native.SteamAPI_ISteamClient_GetISteamRemoteStorage(steamClient, steamUser, steamPipe, SteamRemoteStorageInterfaceVersion);
        }

        private static void SetQueryLanguage(IntPtr steamUgc, ulong query, WorkshopQueryLanguage language, Action<string> log)
        {
            if (language == null || String.IsNullOrWhiteSpace(language.Code))
            {
                return;
            }

            bool ok = NativeSetString(delegate(IntPtr p)
            {
                return Native.SteamAPI_ISteamUGC_SetLanguage(steamUgc, query, p);
            }, language.Code);
            if (!ok)
            {
                log("警告：设置工坊查询语言失败：" + language.Name + "。");
            }
        }

        private static void TrySetAllowCachedResponse(IntPtr steamUgc, ulong query, uint maxAgeSeconds, Action<string> log)
        {
            try
            {
                if (!Native.SteamAPI_ISteamUGC_SetAllowCachedResponse(steamUgc, query, maxAgeSeconds))
                {
                    log("警告：设置工坊查询缓存时间失败。");
                }
            }
            catch (EntryPointNotFoundException)
            {
                log("当前 steam_api.dll 不支持 SetAllowCachedResponse，工坊详情查询可能读取到 Steam 缓存。");
            }
        }

        private delegate bool NativeStringSetter(IntPtr utf8);
        private delegate ulong NativeStringSubmitter(IntPtr utf8);
        private delegate T SteamTagsAction<T>(ref SteamParamStringArray tags);

        private static bool NativeSetString(NativeStringSetter setter, string value)
        {
            IntPtr ptr = StringToUtf8(value ?? "");
            try
            {
                return setter(ptr);
            }
            finally
            {
                Marshal.FreeHGlobal(ptr);
            }
        }

        private static ulong NativeSetString(NativeStringSubmitter setter, string value)
        {
            IntPtr ptr = StringToUtf8(value ?? "");
            try
            {
                return setter(ptr);
            }
            finally
            {
                Marshal.FreeHGlobal(ptr);
            }
        }

        private static ulong NativeSetStringOrNull(NativeStringSubmitter setter, string value)
        {
            IntPtr ptr = IntPtr.Zero;
            if (!String.IsNullOrEmpty(value))
            {
                ptr = StringToUtf8(value);
            }
            try
            {
                return setter(ptr);
            }
            finally
            {
                if (ptr != IntPtr.Zero)
                {
                    Marshal.FreeHGlobal(ptr);
                }
            }
        }

        private static bool NativeSetTags(IntPtr steamUgc, ulong updateHandle, string[] tags)
        {
            return WithSteamTags(tags, delegate(ref SteamParamStringArray array)
            {
                return Native.SteamAPI_ISteamUGC_SetItemTags(steamUgc, updateHandle, ref array);
            });
        }

        private static T WithSteamTags<T>(string[] tags, SteamTagsAction<T> action)
        {
            if (tags == null)
            {
                tags = new string[0];
            }

            IntPtr strings = IntPtr.Zero;
            var tagPointers = new IntPtr[tags.Length];
            try
            {
                if (tags.Length > 0)
                {
                    strings = Marshal.AllocHGlobal(IntPtr.Size * tags.Length);
                    for (int i = 0; i < tags.Length; i++)
                    {
                        tagPointers[i] = StringToUtf8(tags[i] ?? "");
                        Marshal.WriteIntPtr(strings, i * IntPtr.Size, tagPointers[i]);
                    }
                }

                var array = new SteamParamStringArray();
                array.Strings = strings;
                array.NumStrings = tags.Length;
                return action(ref array);
            }
            finally
            {
                for (int i = 0; i < tagPointers.Length; i++)
                {
                    if (tagPointers[i] != IntPtr.Zero)
                    {
                        Marshal.FreeHGlobal(tagPointers[i]);
                    }
                }
                if (strings != IntPtr.Zero)
                {
                    Marshal.FreeHGlobal(strings);
                }
            }
        }

        private static IntPtr StringToUtf8(string value)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(value ?? "");
            IntPtr ptr = Marshal.AllocHGlobal(bytes.Length + 1);
            Marshal.Copy(bytes, 0, ptr, bytes.Length);
            Marshal.WriteByte(ptr, bytes.Length, 0);
            return ptr;
        }

        private static void Require(bool ok, string operation)
        {
            if (!ok)
            {
                throw new InvalidOperationException(operation + " 返回失败。");
            }
        }

        private static bool IsCallbackReadFailure(Exception ex, string operation)
        {
            string message = ex == null ? "" : (ex.Message ?? "");
            return message.IndexOf(operation, StringComparison.OrdinalIgnoreCase) >= 0
                && message.IndexOf("回调读取失败", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static bool IsSteamCallMarkedFailed(Exception ex, string operation)
        {
            string message = ex == null ? "" : (ex.Message ?? "");
            return message.IndexOf(operation, StringComparison.OrdinalIgnoreCase) >= 0
                && message.IndexOf("Steam 回调标记失败", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static WorkshopQueryLanguage[] CreateWorkshopQueryLanguages()
        {
            return new WorkshopQueryLanguage[]
            {
                new WorkshopQueryLanguage("schinese", "中文", true),
                new WorkshopQueryLanguage("english", "英文", false)
            };
        }

        private static bool MergePublishedItem(
            Dictionary<ulong, WorkshopPublishedItem> resultById,
            SteamUgcDetails details,
            string metadata,
            string previewUrl,
            string queryTags,
            WorkshopQueryLanguage language)
        {
            WorkshopPublishedItem item;
            bool added = false;
            if (!resultById.TryGetValue(details.PublishedFileId, out item))
            {
                item = new WorkshopPublishedItem();
                item.PublishedFileId = details.PublishedFileId;
                resultById[details.PublishedFileId] = item;
                added = true;
            }

            string title = Utf8String(details.Title);
            item.AppId = details.ConsumerAppId;
            item.OwnerSteamId = details.SteamIdOwner;
            string description = Utf8String(details.Description);
            if (language != null && language.IsChinese)
            {
                if (!String.IsNullOrWhiteSpace(title))
                {
                    item.TitleChinese = title;
                }
                if (!String.IsNullOrWhiteSpace(description))
                {
                    item.DescriptionChinese = description;
                }
            }
            else
            {
                if (!String.IsNullOrWhiteSpace(title))
                {
                    item.TitleEnglish = title;
                }
                if (!String.IsNullOrWhiteSpace(description))
                {
                    item.DescriptionEnglish = description;
                }
            }

            string tags = queryTags;
            bool tagsLoaded = tags != null;
            if (!tagsLoaded)
            {
                tags = Utf8String(details.Tags);
                tagsLoaded = !String.IsNullOrWhiteSpace(tags);
            }
            if (tagsLoaded && (!String.IsNullOrWhiteSpace(tags) || !item.TagsLoaded))
            {
                item.Tags = tags;
                item.TagsLoaded = true;
            }

            string metadataVersion = ReadVersionFromMetadata(metadata);
            if (!String.IsNullOrWhiteSpace(metadataVersion))
            {
                item.Version = metadataVersion;
            }
            else if (String.IsNullOrWhiteSpace(item.Version))
            {
                item.Version = ReadVersionFromTags(item.Tags);
            }
            if (!String.IsNullOrWhiteSpace(previewUrl))
            {
                item.PreviewUrl = previewUrl;
            }
            if (details.TimeUpdated != 0 && details.TimeUpdated >= item.TimeUpdated)
            {
                item.TimeUpdated = details.TimeUpdated;
            }
            item.Visibility = details.Visibility;
            item.Title = FirstNonEmpty(item.TitleChinese, item.TitleEnglish, item.Title, title);
            item.Description = FirstNonEmpty(item.DescriptionChinese, item.DescriptionEnglish, item.Description, description);
            return added;
        }

        private static bool TryGetQueryResult(IntPtr steamUgc, ulong query, uint index, out SteamUgcDetails details)
        {
            int size = Marshal.SizeOf(typeof(SteamUgcDetails));
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                bool ok = Native.SteamAPI_ISteamUGC_GetQueryUGCResult(steamUgc, query, index, buffer);
                if (!ok)
                {
                    details = new SteamUgcDetails();
                    return false;
                }
                details = (SteamUgcDetails)Marshal.PtrToStructure(buffer, typeof(SteamUgcDetails));
                return true;
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        private static string GetQueryMetadata(IntPtr steamUgc, ulong query, uint index)
        {
            IntPtr buffer = Marshal.AllocHGlobal(MetadataBufferSize);
            try
            {
                Marshal.WriteByte(buffer, 0);
                bool ok = Native.SteamAPI_ISteamUGC_GetQueryUGCMetadata(steamUgc, query, index, buffer, (uint)MetadataBufferSize);
                return ok ? PtrToUtf8String(buffer, MetadataBufferSize) : "";
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        private static string GetQueryPreviewUrl(IntPtr steamUgc, ulong query, uint index)
        {
            const int PreviewUrlBufferSize = 1024;
            IntPtr buffer = Marshal.AllocHGlobal(PreviewUrlBufferSize);
            try
            {
                Marshal.WriteByte(buffer, 0);
                bool ok = Native.SteamAPI_ISteamUGC_GetQueryUGCPreviewURL(steamUgc, query, index, buffer, (uint)PreviewUrlBufferSize);
                return ok ? PtrToUtf8String(buffer, PreviewUrlBufferSize) : "";
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        private static string GetQueryTags(IntPtr steamUgc, ulong query, uint index)
        {
            const int TagBufferSize = 512;
            uint tagCount;
            try
            {
                tagCount = Native.SteamAPI_ISteamUGC_GetQueryUGCNumTags(steamUgc, query, index);
            }
            catch (EntryPointNotFoundException)
            {
                return null;
            }

            var tags = new List<string>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            IntPtr buffer = Marshal.AllocHGlobal(TagBufferSize);
            try
            {
                for (uint tagIndex = 0; tagIndex < tagCount; tagIndex++)
                {
                    Marshal.WriteByte(buffer, 0);
                    bool ok;
                    try
                    {
                        ok = Native.SteamAPI_ISteamUGC_GetQueryUGCTag(steamUgc, query, index, tagIndex, buffer, (uint)TagBufferSize);
                    }
                    catch (EntryPointNotFoundException)
                    {
                        return null;
                    }
                    if (!ok)
                    {
                        continue;
                    }

                    string tag = PtrToUtf8String(buffer, TagBufferSize).Trim();
                    if (tag.Length == 0 || seen.Contains(tag))
                    {
                        continue;
                    }

                    seen.Add(tag);
                    tags.Add(tag);
                }
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
            return String.Join(", ", tags.ToArray());
        }

        private static string ReadVersionFromMetadata(string metadata)
        {
            if (String.IsNullOrWhiteSpace(metadata))
            {
                return "";
            }

            string[] lines = metadata.Replace("\r", "\n").Split(new char[] { '\n' }, StringSplitOptions.RemoveEmptyEntries);
            foreach (string line in lines)
            {
                string trimmed = line.Trim();
                int separator = trimmed.IndexOf(':');
                if (separator < 0)
                {
                    separator = trimmed.IndexOf('=');
                }
                if (separator <= 0)
                {
                    continue;
                }

                string key = trimmed.Substring(0, separator).Trim();
                if (key.Equals("version", StringComparison.OrdinalIgnoreCase))
                {
                    return trimmed.Substring(separator + 1).Trim().Trim('"', '\'');
                }
            }

            return "";
        }

        private static string ReadVersionFromTags(string tags)
        {
            if (String.IsNullOrWhiteSpace(tags))
            {
                return "";
            }

            Match match = Regex.Match(
                tags,
                @"(?:^|[\s,;|，；\(\（])version\s*[:=]\s*(?<version>[^\s,;|\)\）]+)",
                RegexOptions.IgnoreCase);
            if (!match.Success)
            {
                return "";
            }
            return match.Groups["version"].Value.Trim().Trim('"', '\'');
        }

        private static string FirstNonEmpty(params string[] values)
        {
            if (values == null)
            {
                return "";
            }

            foreach (string value in values)
            {
                if (!String.IsNullOrWhiteSpace(value))
                {
                    return value.Trim();
                }
            }
            return "";
        }

        private static string BuildWorkshopMetadata(string version, string versionCompatible)
        {
            var lines = new List<string>();
            if (!String.IsNullOrWhiteSpace(version))
            {
                lines.Add("version:" + version.Trim());
            }
            if (!String.IsNullOrWhiteSpace(versionCompatible))
            {
                lines.Add("version_compatible:" + versionCompatible.Trim());
            }
            return String.Join("\n", lines.ToArray());
        }

        private static string Utf8String(byte[] bytes)
        {
            if (bytes == null || bytes.Length == 0)
            {
                return "";
            }

            int length = 0;
            while (length < bytes.Length && bytes[length] != 0)
            {
                length++;
            }
            if (length == 0)
            {
                return "";
            }
            return Encoding.UTF8.GetString(bytes, 0, length);
        }

        private static string PtrToUtf8String(IntPtr ptr, int maxLength)
        {
            if (ptr == IntPtr.Zero || maxLength <= 0)
            {
                return "";
            }

            int length = 0;
            while (length < maxLength && Marshal.ReadByte(ptr, length) != 0)
            {
                length++;
            }
            if (length == 0)
            {
                return "";
            }

            byte[] bytes = new byte[length];
            Marshal.Copy(ptr, bytes, 0, length);
            return Encoding.UTF8.GetString(bytes, 0, length);
        }

        private static T WaitForCallResult<T>(
            IntPtr steamUtils,
            ulong call,
            int callbackId,
            string operation,
            ulong updateHandle,
            IntPtr steamUgc,
            Action<string> log)
        {
            if (call == 0)
            {
                throw new InvalidOperationException(operation + " 没有返回有效的 SteamAPICall。");
            }

            int size = Marshal.SizeOf(typeof(T));
            DateTime started = DateTime.UtcNow;
            DateTime lastProgressLog = DateTime.MinValue;
            string lastProgress = "";

            while (true)
            {
                Native.SteamAPI_RunCallbacks();

                byte failedByte;
                bool completed = Native.SteamAPI_ISteamUtils_IsAPICallCompleted(steamUtils, call, out failedByte);
                if (completed)
                {
                    IntPtr buffer = Marshal.AllocHGlobal(size);
                    try
                    {
                        bool failed;
                        bool ok = Native.SteamAPI_ISteamUtils_GetAPICallResult(steamUtils, call, buffer, size, callbackId, out failedByte);
                        failed = failedByte != 0;
                        if (!ok)
                        {
                            throw new InvalidOperationException(operation + " 回调读取失败（callback=" + callbackId + "，size=" + size + "，failed=" + failed + "）。");
                        }
                        if (failed)
                        {
                            throw new InvalidOperationException(operation + " Steam 回调标记失败（callback=" + callbackId + "，size=" + size + "）。");
                        }
                        return (T)Marshal.PtrToStructure(buffer, typeof(T));
                    }
                    finally
                    {
                        Marshal.FreeHGlobal(buffer);
                    }
                }

                if (updateHandle != 0 && updateHandle != InvalidUpdateHandle && steamUgc != IntPtr.Zero)
                {
                    ulong processed;
                    ulong total;
                    int status = Native.SteamAPI_ISteamUGC_GetItemUpdateProgress(steamUgc, updateHandle, out processed, out total);
                    string progress = FormatProgress(status, processed, total);
                    if (progress != lastProgress && (DateTime.UtcNow - lastProgressLog).TotalMilliseconds > 800)
                    {
                        log(progress);
                        lastProgress = progress;
                        lastProgressLog = DateTime.UtcNow;
                    }
                }

                double timeoutMinutes = operation.StartsWith("SendQuery", StringComparison.Ordinal) ? 1 : 120;
                if ((DateTime.UtcNow - started).TotalMinutes > timeoutMinutes)
                {
                    throw new TimeoutException(operation + " 等待超过 " + timeoutMinutes + " 分钟。");
                }

                Thread.Sleep(100);
            }
        }

        private static string FormatProgress(int status, ulong processed, ulong total)
        {
            string statusText = UpdateStatusName(status);
            if (total > 0)
            {
                double percent = Math.Min(100.0, processed * 100.0 / total);
                return statusText + " " + percent.ToString("0.0") + "% (" + processed + "/" + total + ")";
            }
            return statusText;
        }

        private static string UpdateStatusName(int status)
        {
            switch (status)
            {
                case 1: return "准备配置";
                case 2: return "准备内容";
                case 3: return "上传内容";
                case 4: return "上传预览图";
                case 5: return "提交更改";
                default: return "等待 Steam";
            }
        }

        private static string ResultName(int result)
        {
            switch (result)
            {
                case 1: return "OK";
                case 2: return "Fail";
                case 3: return "NoConnection";
                case 5: return "InvalidPassword";
                case 8: return "InvalidParam";
                case 9: return "FileNotFound";
                case 15: return "AccessDenied";
                case 16: return "Timeout";
                case 20: return "ServiceUnavailable";
                case 25: return "LimitExceeded";
                case 50: return "InsufficientPrivilege";
                default: return "EResult " + result;
            }
        }

        [StructLayout(LayoutKind.Sequential, Pack = 8)]
        private struct SteamUgcQueryCompleted
        {
            public ulong Handle;
            public int Result;
            public uint NumResultsReturned;
            public uint TotalMatchingResults;
            [MarshalAs(UnmanagedType.I1)]
            public bool CachedData;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 8)]
        private struct SteamUgcDetails
        {
            public ulong PublishedFileId;
            public int Result;
            public int FileType;
            public uint CreatorAppId;
            public uint ConsumerAppId;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 129)]
            public byte[] Title;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 8000)]
            public byte[] Description;
            public ulong SteamIdOwner;
            public uint TimeCreated;
            public uint TimeUpdated;
            public uint TimeAddedToUserList;
            public int Visibility;
            [MarshalAs(UnmanagedType.I1)]
            public bool Banned;
            [MarshalAs(UnmanagedType.I1)]
            public bool AcceptedForUse;
            [MarshalAs(UnmanagedType.I1)]
            public bool TagsTruncated;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 1025)]
            public byte[] Tags;
            public ulong File;
            public ulong PreviewFile;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 260)]
            public byte[] FileName;
            public int FileSize;
            public int PreviewFileSize;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 256)]
            public byte[] Url;
            public uint VotesUp;
            public uint VotesDown;
            public float Score;
            public uint NumChildren;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 8)]
        private struct CreateItemResult
        {
            public int Result;
            public ulong PublishedFileId;
            [MarshalAs(UnmanagedType.I1)]
            public bool UserNeedsToAcceptWorkshopLegalAgreement;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 8)]
        private struct SubmitItemUpdateResult
        {
            public int Result;
            [MarshalAs(UnmanagedType.I1)]
            public bool UserNeedsToAcceptWorkshopLegalAgreement;
            public ulong PublishedFileId;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 8)]
        private struct RemoteStorageFileShareResult
        {
            public int Result;
            public ulong File;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 260)]
            public byte[] Filename;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 8)]
        private struct RemoteStoragePublishFileResult
        {
            public int Result;
            public ulong PublishedFileId;
            [MarshalAs(UnmanagedType.I1)]
            public bool UserNeedsToAcceptWorkshopLegalAgreement;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 8)]
        private struct RemoteStorageUpdatePublishedFileResult
        {
            public int Result;
            public ulong PublishedFileId;
            [MarshalAs(UnmanagedType.I1)]
            public bool UserNeedsToAcceptWorkshopLegalAgreement;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct SteamParamStringArray
        {
            public IntPtr Strings;
            public int NumStrings;
        }

        private sealed class StagedContentStats
        {
            public int CopiedFiles;
            public int SkippedFiles;
            public int SkippedDirectories;
        }

        private sealed class WorkshopQueryLanguage
        {
            public readonly string Code;
            public readonly string Name;
            public readonly bool IsChinese;

            public WorkshopQueryLanguage(string code, string name, bool isChinese)
            {
                Code = code;
                Name = name;
                IsChinese = isChinese;
            }
        }

        private static class Native
        {
            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_Init();

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern void SteamAPI_Shutdown();

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern void SteamAPI_RunCallbacks();

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_IsSteamRunning();

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern IntPtr SteamClient();

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern int SteamAPI_GetHSteamUser();

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern int SteamAPI_GetHSteamPipe();

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern IntPtr SteamAPI_ISteamClient_GetISteamUser(IntPtr instancePtr, int hSteamUser, int hSteamPipe, [MarshalAs(UnmanagedType.LPStr)] string version);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern IntPtr SteamAPI_ISteamClient_GetISteamUtils(IntPtr instancePtr, int hSteamPipe, [MarshalAs(UnmanagedType.LPStr)] string version);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern IntPtr SteamAPI_ISteamClient_GetISteamUGC(IntPtr instancePtr, int hSteamUser, int hSteamPipe, [MarshalAs(UnmanagedType.LPStr)] string version);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern IntPtr SteamAPI_ISteamClient_GetISteamRemoteStorage(IntPtr instancePtr, int hSteamUser, int hSteamPipe, [MarshalAs(UnmanagedType.LPStr)] string version);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUser_BLoggedOn(IntPtr instancePtr);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern ulong SteamAPI_ISteamUser_GetSteamID(IntPtr instancePtr);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern ulong SteamAPI_ISteamUGC_CreateItem(IntPtr instancePtr, uint consumerAppId, int fileType);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern ulong SteamAPI_ISteamUGC_CreateQueryUGCDetailsRequest(IntPtr instancePtr, ulong[] publishedFileIds, uint numPublishedFileIds);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern ulong SteamAPI_ISteamUGC_CreateQueryUserUGCRequest(IntPtr instancePtr, uint accountId, int listType, int matchingUgcType, int sortOrder, uint creatorAppId, uint consumerAppId, uint page);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern ulong SteamAPI_ISteamUGC_SendQueryUGCRequest(IntPtr instancePtr, ulong queryHandle);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_SetReturnMetadata(IntPtr instancePtr, ulong queryHandle, [MarshalAs(UnmanagedType.I1)] bool returnMetadata);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_SetReturnLongDescription(IntPtr instancePtr, ulong queryHandle, [MarshalAs(UnmanagedType.I1)] bool returnLongDescription);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_SetAllowCachedResponse(IntPtr instancePtr, ulong queryHandle, uint maxAgeSeconds);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_SetLanguage(IntPtr instancePtr, ulong queryHandle, IntPtr language);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_GetQueryUGCResult(IntPtr instancePtr, ulong queryHandle, uint index, IntPtr details);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_GetQueryUGCMetadata(IntPtr instancePtr, ulong queryHandle, uint index, IntPtr metadata, uint metadataSize);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_GetQueryUGCPreviewURL(IntPtr instancePtr, ulong queryHandle, uint index, IntPtr url, uint urlSize);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern uint SteamAPI_ISteamUGC_GetQueryUGCNumTags(IntPtr instancePtr, ulong queryHandle, uint index);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_GetQueryUGCTag(IntPtr instancePtr, ulong queryHandle, uint index, uint indexTag, IntPtr value, uint valueSize);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_ReleaseQueryUGCRequest(IntPtr instancePtr, ulong queryHandle);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern ulong SteamAPI_ISteamUGC_StartItemUpdate(IntPtr instancePtr, uint consumerAppId, ulong publishedFileId);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_SetItemTitle(IntPtr instancePtr, ulong updateHandle, IntPtr title);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_SetItemDescription(IntPtr instancePtr, ulong updateHandle, IntPtr description);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_SetItemMetadata(IntPtr instancePtr, ulong updateHandle, IntPtr metadata);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_SetItemContent(IntPtr instancePtr, ulong updateHandle, IntPtr contentFolder);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_SetItemPreview(IntPtr instancePtr, ulong updateHandle, IntPtr previewFile);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_SetItemTags(IntPtr instancePtr, ulong updateHandle, ref SteamParamStringArray tags);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUGC_SetItemVisibility(IntPtr instancePtr, ulong updateHandle, int visibility);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern ulong SteamAPI_ISteamUGC_SubmitItemUpdate(IntPtr instancePtr, ulong updateHandle, IntPtr changeNote);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamRemoteStorage_FileWrite(IntPtr instancePtr, IntPtr file, byte[] data, int dataSize);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamRemoteStorage_FileDelete(IntPtr instancePtr, IntPtr file);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamRemoteStorage_FileExists(IntPtr instancePtr, IntPtr file);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern int SteamAPI_ISteamRemoteStorage_GetFileSize(IntPtr instancePtr, IntPtr file);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern ulong SteamAPI_ISteamRemoteStorage_FileShare(IntPtr instancePtr, IntPtr file);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern ulong SteamAPI_ISteamRemoteStorage_PublishWorkshopFile(IntPtr instancePtr, IntPtr file, IntPtr previewFile, uint consumerAppId, IntPtr title, IntPtr description, int visibility, ref SteamParamStringArray tags, int workshopFileType);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern ulong SteamAPI_ISteamRemoteStorage_CreatePublishedFileUpdateRequest(IntPtr instancePtr, ulong publishedFileId);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamRemoteStorage_UpdatePublishedFileFile(IntPtr instancePtr, ulong updateHandle, IntPtr file);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamRemoteStorage_UpdatePublishedFilePreviewFile(IntPtr instancePtr, ulong updateHandle, IntPtr previewFile);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamRemoteStorage_UpdatePublishedFileTitle(IntPtr instancePtr, ulong updateHandle, IntPtr title);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamRemoteStorage_UpdatePublishedFileDescription(IntPtr instancePtr, ulong updateHandle, IntPtr description);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamRemoteStorage_UpdatePublishedFileVisibility(IntPtr instancePtr, ulong updateHandle, int visibility);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamRemoteStorage_UpdatePublishedFileTags(IntPtr instancePtr, ulong updateHandle, ref SteamParamStringArray tags);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamRemoteStorage_UpdatePublishedFileSetChangeDescription(IntPtr instancePtr, ulong updateHandle, IntPtr changeDescription);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern ulong SteamAPI_ISteamRemoteStorage_CommitPublishedFileUpdate(IntPtr instancePtr, ulong updateHandle);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            public static extern int SteamAPI_ISteamUGC_GetItemUpdateProgress(IntPtr instancePtr, ulong updateHandle, out ulong bytesProcessed, out ulong bytesTotal);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUtils_IsAPICallCompleted(IntPtr instancePtr, ulong steamApiCall, out byte failed);

            [DllImport("steam_api.dll", CallingConvention = CallingConvention.Cdecl)]
            [return: MarshalAs(UnmanagedType.I1)]
            public static extern bool SteamAPI_ISteamUtils_GetAPICallResult(IntPtr instancePtr, ulong steamApiCall, IntPtr callback, int callbackSize, int callbackExpected, out byte failed);
        }
    }
}
