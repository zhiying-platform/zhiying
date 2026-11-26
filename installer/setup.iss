; ============================================================
; 知映 zhiying — Windows 离线安装器（Inno Setup 6）
; 中文界面 + 组件勾选 + PG 初始化 + 卸载器
;
; 构建（推荐，自动读 VERSION 文件）:
;   powershell -File installer\build-installer.ps1
; 直接调用（需自己传参）:
;   ISCC.exe /DMyAppVersion=1.2.0 setup.iss
; ============================================================

#define MyAppName "知映 zhiying"
; 版本：优先取命令行 /DMyAppVersion，否则回退到默认值
#ifndef MyAppVersion
  #define MyAppVersion "1.4.0"
#endif
#define MyAppPublisher "zhiying-platform"
#define MyAppExeName "zhiying.exe"
; 输出文件名：正式包不带版本号（规范），自测包加 -dev 区分
#ifndef OutputName
  #define OutputName "zhiying-setup"
#endif

[Setup]
; 安装器自身图标（exe/标题栏/任务栏，卸载器自动沿用）：此前缺失 → 显示 Inno 默认图标
SetupIconFile=..\assets\logo\final\zhiying.ico
WizardImageFile=..\assets\logo\final\wizard-large.png
WizardSmallImageFile=..\assets\logo\final\wizard-small.png
AppId={{8C7B6A5D-4E3F-4B2A-9C1D-0F2E3D4C5B6A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\zhiying
DefaultGroupName=知映 zhiying
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename={#OutputName}
; 快速构建（-Fast）：大件（python/pg）不压缩，编译从 370s 降到 ~68s，供迭代自测
#ifndef FastBuild
  #define FastBuild 0
#endif
#if FastBuild
Compression=none
SolidCompression=no
#else
Compression=lzma2/normal
SolidCompression=yes
#endif
WizardStyle=modern
; 中文界面
ShowLanguageDialog=no
UninstallDisplayIcon={uninstallexe}
; 按用户安装（免 UAC 提权，安装目录与其他用户数据同域，避免混合权限告警）
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Types]
; 只有两个真实选项（core 固定 + pg 可选），因此不提供「自定义」——
; 选了自定义也只能勾一个组件，纯属冗余。
; 注：Description 不支持 \n 换行，只能单行，故把产出物写在同一行。
Name: "full"; Description: "完整安装（推荐）—— 视频转写 + md 文档 + 摘要 + skill 包 + 知识库检索问答"
Name: "compact"; Description: "精简安装 —— 视频转写 + md 文档 + 摘要 + skill 包（不装数据库，无检索/问答）"

[Components]
Name: "core"; Description: "核心运行环境（Python + 后端 + Web 界面）—— 产出：转写、md 文档、摘要、skill 包"; Types: full compact; Flags: fixed
Name: "pg"; Description: "知识库（PostgreSQL + pgvector，约 300MB）—— 产出：向量检索、问答溯源"; Types: full

[Files]
; --- Python 运行时 + 全部依赖 + zhiying 包（标准布局：python\Lib\site-packages，site 扫描 .pth 才生效）---
#if FastBuild
Source: "stage\python\*"; DestDir: "{app}\runtime\python"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression
#else
Source: "stage\python\*"; DestDir: "{app}\runtime\python"; Flags: recursesubdirs createallsubdirs ignoreversion
#endif

; --- 前端 dist ---
Source: "stage\web\*"; DestDir: "{app}\web"; Flags: recursesubdirs createallsubdirs ignoreversion

; --- PostgreSQL（组件 pg）---
#if FastBuild
Source: "stage\pg\*"; DestDir: "{app}\runtime\pg"; Components: pg; Flags: recursesubdirs createallsubdirs ignoreversion nocompression
#else
Source: "stage\pg\*"; DestDir: "{app}\runtime\pg"; Components: pg; Flags: recursesubdirs createallsubdirs ignoreversion
#endif

; --- 启动/管理脚本（安装版脚本组，安装后 {app}\scripts）---
Source: "..\scripts\installed\start-core.cmd"; DestDir: "{app}\scripts"; DestName: "start.cmd"; Flags: ignoreversion
Source: "..\scripts\installed\stop.cmd"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\installed\zhiying-cli.cmd"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\installed\zhiying-mcp.cmd"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\installed\pg-setup-installed.cmd"; DestDir: "{app}\scripts"; DestName: "pg-setup.cmd"; Flags: ignoreversion

; --- 文档 ---
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\installation-readme.txt"; DestDir: "{app}"; DestName: "安装说明.txt"; Flags: ignoreversion

[Dirs]
; 数据目录放用户目录（升级不丢数据）
Name: "{userappdata}\zhiying"

[Icons]
; 直接指向 pythonw.exe（无控制台程序）：双击不会弹 cmd 窗口。
; tray.py 自我解析安装路径，自行完成「起 PG → 建库建表 → 起服务 → 开浏览器 → 托盘驻留」。
Name: "{group}\知映 zhiying"; Filename: "{app}\runtime\python\pythonw.exe"; Parameters: "-m zhiying.tray"; WorkingDir: "{app}"; IconFilename: "{app}\runtime\python\Lib\site-packages\zhiying\assets\zhiying.ico"
Name: "{group}\停止服务"; Filename: "{app}\scripts\stop.cmd"; WorkingDir: "{app}"
Name: "{group}\卸载 知映 zhiying"; Filename: "{uninstallexe}"
Name: "{group}\安装说明"; Filename: "{app}\安装说明.txt"
Name: "{userdesktop}\知映 zhiying"; Filename: "{app}\runtime\python\pythonw.exe"; Parameters: "-m zhiying.tray"; WorkingDir: "{app}"; IconFilename: "{app}\runtime\python\Lib\site-packages\zhiying\assets\zhiying.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式(&D)"; GroupDescription: "附加任务:"

[Run]
; postinstall 启动也走 pythonw，安装完成后不会留一个 cmd 窗口
Filename: "{app}\runtime\python\pythonw.exe"; Parameters: "-m zhiying.tray"; WorkingDir: "{app}"; Description: "立即启动 知映 zhiying"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; 覆盖安装（升级）时先清理：
; 1) 旧版前端产物（含旧 hash 命名 chunk——Copy-Item 时代曾积存两套 JS，页面加载到旧版）
;    本条随 /MIR 镜像方案兜底：确保升级后 web 目录与安装包严格一致
Type: filesandordirs; Name: "{app}\web"
; 2) 旧版后端源码包（含旧 __pycache__；新版源码由 [Files] 重新安装）
Type: filesandordirs; Name: "{app}\runtime\python\Lib\site-packages\zhiying"

[UninstallDelete]
; 清理卸载后残留（数据目录 {userappdata}\zhiying 由 [Code] 按用户选择处理）
Type: filesandordirs; Name: "{app}\runtime\python\Lib\site-packages\pip"
; .env 由安装器 [Code] 写入，不在 [Files] 清单内
Type: files; Name: "{app}\runtime\python\Lib\.env"
Type: filesandordirs; Name: "{app}\runtime\python\Lib\site-packages\zhiying\__pycache__"

[Code]
var
  gDeletePG: Boolean;
  gDeleteUserData: Boolean;
  gDataDir: String;
  gDowngradeConfirmed: Boolean;

// 目录下是否存在任何文件或子目录
function HasFilesIn(const Dir: String): Boolean;
var
  FindRec: TFindRec;
  Found: Boolean;
begin
  Found := False;
  if DirExists(Dir) and FindFirst(AddBackslash(Dir) + '*', FindRec) then
  begin
    repeat
      if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        Found := True;
    until (Found) or (not FindNext(FindRec));
    FindClose(FindRec);
  end;
  Result := Found;
end;

// 解析数据目录：优先读 .env 中 ZHIYING_DATA（安装时指定的存储路径）
function ResolveDataDir(): String;
var
  envFile: String;
  raw: AnsiString;
  s: String;
  val: String;
  p: Integer;
begin
  Result := ExpandConstant('{userappdata}\zhiying');
  envFile := ExpandConstant('{app}\runtime\python\Lib\.env');
  if FileExists(envFile) and LoadStringFromFile(envFile, raw) then
  begin
    s := String(raw);
    p := Pos('ZHIYING_DATA=', s);
    if p > 0 then
    begin
      val := Copy(s, p + Length('ZHIYING_DATA='), Length(s));
      p := Pos(#13, val);
      if p > 0 then val := Copy(val, 1, p - 1);
      p := Pos(#10, val);
      if p > 0 then val := Copy(val, 1, p - 1);
      val := Trim(val);
      if val <> '' then Result := val;
    end;
  end;
end;

// 停止运行中的服务：杀 8600（含托盘 pythonw）+ pg_ctl stop 嵌入式 PG
procedure StopRunningService();
var
  rc: Integer;
  pgctl: String;
  pgdata: String;
begin
  Exec(ExpandConstant('{cmd}'), '/C for /f "tokens=5" %p in (''netstat -ano ^| findstr ":8600" ^| findstr "LISTENING"'') do taskkill /PID %p /F >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, rc);
  pgctl := ExpandConstant('{app}\runtime\pg\bin\pg_ctl.exe');
  pgdata := ResolveDataDir() + '\pg';
  if FileExists(pgctl) and DirExists(pgdata) then
    Exec('"' + pgctl + '"', '-D "' + pgdata + '" stop -m fast', '', SW_HIDE, ewWaitUntilTerminated, rc);
end;

// 服务是否在运行
function ServiceRunning(): Boolean;
var
  rc: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/C netstat -ano | findstr ":8600" | findstr "LISTENING" >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, rc);
  Result := (rc = 0);
end;

// 安装前：检测到服务在运行则弹窗确认，用户同意后停服务
function InitializeSetup(): Boolean;
begin
  Result := True;
  if ServiceRunning() then
  begin
    if MsgBox('检测到知映服务正在运行。' + #13#10 + #13#10 +
             '继续安装需要先停止服务（已保存的数据不会丢失）。' + #13#10 +
             '是否停止服务并继续安装？', mbConfirmation, MB_YESNO) = IDYES then
    begin
      StopRunningService();
      Sleep(2000);
    end
    else
      Result := False;
  end;
end;

// 组件选择页「下一步」：利用 Inno 内置「组件已存在」警告弹窗（文案已改为降级确认）
// 用户点「是」继续才走到这里 → 记录降级意图，ssPostInstall 执行清理；
// 点「否」时 Inno 直接返回组件页，本事件不触发 → 维持完整安装。
function NextButtonClick(CurPageId: Integer): Boolean;
begin
  Result := True;
  if WizardSilent() then
    exit;  // 静默安装不弹窗，安全默认维持完整安装
  if CurPageId = wpSelectComponents then
  begin
    // 重置必须只在本页发生：NextButtonClick 对每一页的「下一步」都触发，
    // 若在顶部无条件重置，后续页面（就绪页）会把降级确认清掉 →
    // ssPostInstall 判断为 False → PG 组件与数据不删（实测 bug：用户确认降级后
    // 组件仍残留，托盘仍拉起 PG，菜单仍是完整菜单）
    gDowngradeConfirmed := False;
    if DirExists(ExpandConstant('{app}\runtime\pg')) and (not WizardIsComponentSelected('pg')) then
    begin
      gDowngradeConfirmed := True;
      gDataDir := ResolveDataDir();
    end;
  end;
end;

// 卸载前：服务停确认 -> 知识库数据取舍 -> 沉淀成果取舍
function InitializeUninstall(): Boolean;
begin
  Result := True;
  gDeletePG := False;
  gDeleteUserData := False;
  gDataDir := ResolveDataDir();

  // 静默卸载（/VERYSILENT）无法交互：停服务但一律保留数据
  if UninstallSilent() then
  begin
    if ServiceRunning() then
    begin
      StopRunningService();
      Sleep(2000);
    end;
    exit;
  end;

  if ServiceRunning() then
  begin
    if MsgBox('知映服务正在运行。' + #13#10 + #13#10 +
             '卸载前需要先停止服务（你的数据不会因此丢失）。' + #13#10 + #13#10 +
             '是否停止服务并继续卸载？', mbConfirmation, MB_YESNO) = IDYES then
    begin
      StopRunningService();
      Sleep(2000);
    end
    else
      Result := False;
  end;

  if Result then
  begin
    // ① 知识库（向量数据库）：有则询问，默认保留
    if DirExists(gDataDir + '\pg') then
    begin
      if MsgBox('检测到已使用知识库功能（向量数据库）。' + #13#10 + #13#10 +
               '位置：' + gDataDir + '\pg' + #13#10 + #13#10 +
               '是否同时删除知识库数据库及其数据？' + #13#10 +
               '选择「否」= 保留，重新安装后可继续使用。',
               mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        gDeletePG := True;
    end;

    // ② 沉淀的 skill 包与 md 文档：默认保留
    if HasFilesIn(gDataDir + '\videos') then
    begin
      if MsgBox('检测到沉淀的知识成果（skill 包与 md 文档）。' + #13#10 + #13#10 +
               '位置：' + gDataDir + '\videos' + #13#10 + #13#10 +
               '这些是你的成果，默认保留。是否要一并彻底删除？' + #13#10 +
               '选择「否」= 保留（可手动备份或迁移）。',
               mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        gDeleteUserData := True;
    end;

    // 全部保留时明确告知位置
    if (not gDeletePG) and (not gDeleteUserData) and DirExists(gDataDir) then
      MsgBox('视频、知识文档与数据库将保留在：' + #13#10 + gDataDir + #13#10 + #13#10 +
             '卸载完成后可手动删除该目录，或重新安装后继续使用。',
             mbInformation, MB_OK);
  end;
end;

// 递归清理运行时生成的 __pycache__（.pyc 不在安装清单内，Inno 不会自动删）
procedure RemovePycacheDirs(const Dir: String);
var
  FindRec: TFindRec;
  Sub: String;
begin
  if not DirExists(Dir) then exit;
  if FindFirst(AddBackslash(Dir) + '*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') and ((FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) then
        begin
          Sub := AddBackslash(Dir) + FindRec.Name;
          if CompareText(FindRec.Name, '__pycache__') = 0 then
            DelTree(Sub, True, True, True)
          else
            RemovePycacheDirs(Sub);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

// 递归清理空的子目录（自底向上），不影响含文件的目录
procedure RemoveEmptySubDirs(const Dir: String);
var
  FindRec: TFindRec;
  Sub: String;
begin
  if not DirExists(Dir) then exit;
  if FindFirst(AddBackslash(Dir) + '*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') and
           ((FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) then
        begin
          Sub := AddBackslash(Dir) + FindRec.Name;
          RemoveEmptySubDirs(Sub);
          if not HasFilesIn(Sub) then
            RemoveDir(Sub);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

// 卸载完成后按用户选择清理数据
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if gDeletePG then
    begin
      DelTree(gDataDir + '\pg', True, True, True);
      DeleteFile(gDataDir + '\pg.port');
      DeleteFile(gDataDir + '\pg.createdb');
      DeleteFile(gDataDir + '\pg.log');
    end;
    if gDeleteUserData then
      DelTree(gDataDir + '\videos', True, True, True);
    // 数据目录已空则一并移除
    if DirExists(gDataDir) and (not HasFilesIn(gDataDir)) then
      RemoveDir(gDataDir);
    // 清理程序目录的运行时残留（__pycache__ 等）；空目录一并移除
    RemovePycacheDirs(ExpandConstant('{app}'));
    RemoveEmptySubDirs(ExpandConstant('{app}'));
    if DirExists(ExpandConstant('{app}')) and (not HasFilesIn(ExpandConstant('{app}'))) then
      RemoveDir(ExpandConstant('{app}'));
  end;
end;

// 写入 .env 于实际读取位置：site-packages\zhiying\envkeys.py 用 parents[2]/.env
// = {app}\runtime\python\Lib\.env（不是 userappdata，也不是 {app} 根）
procedure CurStepChanged(CurStep: TSetupStep);
var
  envContent: String;
  envPath: String;
  pgData: String;
  rc: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    envPath := ExpandConstant('{app}\runtime\python\Lib\.env');
    if not FileExists(envPath) then
    begin
      envContent :=
        'ZHIYING_HOME=' + ExpandConstant('{app}') + #13#10 +
        'ZHIYING_DATA=' + ExpandConstant('{userappdata}\zhiying') + #13#10 +
        'ZHIYING_WEB_DIST=' + ExpandConstant('{app}\web') + #13#10;
      SaveStringToFile(envPath, envContent, False);
    end;
    // 预初始化数据库（选了 pg 组件时）：把 initdb 提前到安装阶段，
    // 首次启动从 ~13s 降到 ~3s（用户实测：装完到浏览器打开有明显等待）。
    // 升级场景已有数据库则不动；静默降级确认后 pg 未选，自然跳过。
    if WizardIsComponentSelected('pg') then
    begin
      pgData := ResolveDataDir() + '\pg';
      if (not FileExists(pgData + '\PG_VERSION')) and
         FileExists(ExpandConstant('{app}\runtime\pg\bin\initdb.exe')) then
      begin
        Exec(ExpandConstant('{app}\runtime\pg\bin\initdb.exe'),
             '-D "' + pgData + '" -U postgres -E UTF8 --locale=C',
             '', SW_HIDE, ewWaitUntilTerminated, rc);
      end;
    end;
    // 降级确认后的清理：移除 PG 组件与知识库数据（用户在内置弹窗点「是」确认）
    // 双保险：必须同时「确认过降级」且「当前确实未选 pg」，防止误删
    if gDowngradeConfirmed and (not WizardIsComponentSelected('pg')) then
    begin
      DelTree(ExpandConstant('{app}\runtime\pg'), True, True, True);
      DelTree(gDataDir + '\pg', True, True, True);
      DeleteFile(gDataDir + '\pg.port');
      DeleteFile(gDataDir + '\pg.createdb');
      DeleteFile(gDataDir + '\pg.log');
    end;
  end;
end;
