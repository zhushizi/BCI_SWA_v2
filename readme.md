打包命令：pyinstaller -n BCI_SWA_NES main.py --hidden-import ui.resources_rc --collect-all PySide6 --add-data "db\BCI_SWA.db;db" --add-data "ui\*.ui;ui" --add-data "infrastructure\config\config.json;infrastructure/config"
注意：ui/pic、ui/resources_rc.py需要手动复制到dist/BCI_SWA_NES/_internal/ui中，否则无法加载到资源

**日志开关**：在 infrastructure/config/config.json 的 "logging" 段统一控制。可设置 "level"（默认 INFO）、"loggers" 按模块名设置级别（DEBUG/INFO/WARNING/ERROR），或设为 "off" 关闭该模块打印。详见 infrastructure/logging_config.py。


需要加三个触发指令，main-->paradigm，方便主控通过程序控制范式
{
   "jsonrpc": "2.0",
   "method": "main.tigger",
   "params":{
               "tigger_target":"paradigm.start_decoding"
            }
}

{
    "jsonrpc": "2.0",
    "method": "main.tigger",
    "params":{
                "tigger_target": "main.stop_session"
             }
}

{
    "jsonrpc": "2.0",
    "method": "main.tigger",
    "params":{
                "tigger_target": "paradigm.shut_down"
             }
}

范式暂停：
msg = {
         "jsonrpc":"2.0",
         "method":"paradigm.Stage",
         "params":{
                     "stage":"rest"
                  }
      }

msg={
      "jsonrpc":"2.0",
      "method": "decoder.Inform",
      "params":{
                  "pretrain":"pretrain_full_completed",
               }
   }
通知解码器患者名、范式
msg={
      "jsonrpc":"2.0",
      "method": "main.Inform",
      "params":{
                  "patient":"当前选择患者名",
                  "paradigm":"当前选择范式名"
               }
   }