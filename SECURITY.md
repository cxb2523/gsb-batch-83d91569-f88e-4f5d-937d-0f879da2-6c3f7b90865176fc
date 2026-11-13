# 安全与数据管理

FtShare Key配置在后台采集器的Secret或受限文件中。网页读取共享缓存，运行数据、原始响应和部署参数保存在私有环境。Mac默认绑定回环地址，由同机Caddy接收HTTPS。

源码包按允许清单生成，发布前执行`npm run check:release`并审阅新增文件、图片与工作流。公开仓库运行模拟数据CI，云端采集流程以模板提供；部署者在自己的运行仓库配置凭据与归档。

发现凭据泄露时，通过服务商撤销并重建Key，检查使用记录。公开Issue提供脱敏复现步骤；启用GitHub Private Vulnerability Reporting后，可通过该渠道报告敏感问题。

数据运营者管理快照、镜像和网站的数据访问范围。[网络与主机配置](docs/security-and-network.md) · [开源发布交接](docs/open-source-release.md)
