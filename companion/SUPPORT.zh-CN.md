# iOS / iPadOS 27.0–27.2 功能与路径清单

这里的“已接入”仅表示代码已经把文件操作接入 worse_query，**不代表已经通过
Xcode 编译、真机写入或重启后功能验证**。当前没有真机测试结果，不能给出功能覆盖率。

| 原版功能 | 原版目标位置 | 本分支状态 |
| --- | --- | --- |
| MobileGestalt：灵动岛、设备名称、启动音、充电上限、轻点唤醒、碰撞 SOS、台前调度、视差、地区标记、Pencil/操作按钮/相机按钮设置、内部存储、AOD 等 | mobilegestaltcache SystemGroup | 已接入；硬件能力、系统是否读取对应键仍需逐项验证 |
| MobileGestalt 的 Liquid Glass 低性能渲染标记 | 同上 | 已接入；与 Liquid Glass 页面中的全局偏好设置不同 |
| 原版“Enable iPadOS” | MG 字段和 CacheData 联合修改 | 当前桥接不支持原版 CacheData 修改，该选项在 27.x 变灰；iPad App Compatibility 等独立 MG 字段不受影响 |
| 自定义 MobileGestalt 键、导出、原始备份、还原 | 同上 | 已接入；禁止更换缓存布局和设备唯一身份字段 |
| PosterBoard 动态壁纸、视频转换后的资源、配置数据库、刷新偏好 | PosterBoard 应用/系统数据容器 | 已接入批量容器传输；容器发现、27.x 资源格式、加载效果待真机验证 |
| PosterBoard 文件夹重置 | PosterBoard 容器中的目录 | 未实现目录删除/还原；设备端预检查拒绝，不能当作已支持 |
| 自定义 Templates | 由模板决定 | SystemGroup、系统容器、应用/插件/AppGroup 容器文件已接入；其他位置整批拒绝 |
| 锁屏脚注 | configurationprofiles SystemGroup | 已接入合并写入，保留其他键；权限和显示效果待验证 |
| 状态栏：运营商、时间、图标、电量、信号等 | `/var/mobile/Library/SpringBoard/statusBarOverrides` | 超出公开 worse_query 容器访问范围 |
| 其余 SpringBoard 选项 | `/var/Managed Preferences/mobile/…` 等 | 超出访问范围；不能用可写的脚注配置文件替代这些目标 |
| Internal Options | Managed Preferences、mobile Library | 超出访问范围；模板明确指向应用容器时仅支持相应容器文件 |
| Liquid Glass 页全局禁用/时钟/底座/HDR等 | Managed Preferences 的 `.GlobalPreferences.plist` | 超出访问范围；MG 低性能标记不能等价替代 |
| 禁用守护进程、屏幕使用时间等 | `/var/db/com.apple.xpc.launchd/disabled.plist`、mobile Library | 超出访问范围 |
| Feature Flags | `/var/preferences/FeatureFlags/Global.plist` | 超出访问范围 |
| Apple Intelligence：GestaltX 式替代路径 | MobileGestalt 的 AI 能力标记、RegionCode、销售地区字段 | 已接入原有 AI/Eligibility 页面；代码与销售地区独立选择，地区代码单独改为 LL 时保留销售后缀；可尝试启用国行 AI，实际可用性取决于设备、系统与 Apple 服务，未真机验证 |
| 原版 AI eligibility 文件与 AI Feature Flags 写入 | `/var/db/eligibilityd`、`/var/preferences/FeatureFlags` | 旧实现的目标路径仍超出访问范围；27.x 页面使用上面的 MG 替代路径，不发送这些文件 |
| EU Eligibility / EU 侧载资格 | `/var/db/os_eligibility`、MobileAsset | 超出访问范围；GestaltX 的地区与 AI 预设不构成 EU 侧载资格解锁证据 |
| 设备伪装 | MG 字段及依赖项 | MG 字段可通过现有自定义键路径写入；原版完整 AI/伪装流程不作兼容承诺 |
| 密码键盘主题 | `/var/mobile/Library/Caches/TelephonyUI-10` | 超出访问范围 |
| 分辨率、RDAR/灵动岛状态栏修复 | Managed Preferences 的 IOMobileGraphicsFamily | 超出访问范围 |
| OTA/thermal 等风险项 | `/var/Managed Preferences`、`/var/db` | 超出访问范围 |
| 跳过设置向导、重建应用状态、恢复 TrustStore | 非容器恢复域 | 不执行；新路径不使用备份恢复流程 |

原版 `.ui` 布局和页面生成文件未修改。原有 AI/Eligibility 页面在 27.x 显示 AI 能力开关和必要的两个地区选择控件，隐藏不可用的旧 eligibility/Feature Flags 操作；旧系统继续使用原页面行为。另调整首页支持提示；明确不支持的页面入口、页内控件、PosterBoard 目录重置和旧恢复设置在 27.0–27.2 统一变灰并显示原因。SpringBoard 页保留脚注，AI/MG 和可用容器模板保持可选，重置对话框中的不支持项目也变灰。切回旧系统时恢复原控件状态。
旧设备留下的已选禁用功能不参与 27.x 文件生成，但保留其旧系统选择；不支持的模板控制项变灰且不应用，删除按钮仍可使用。对于仍进入传输层的未知或非法目标路径，在发送前拒绝整批操作。

如果要覆盖表中的非容器路径，需要额外的访问能力或已证明等效的实现。
[GestaltX](https://github.com/huamidev/GestaltX) 同样不能作为这些路径已经可写的依据。
