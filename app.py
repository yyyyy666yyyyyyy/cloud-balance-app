import glob
import json
import os
import threading
import time
import traceback
import warnings
import pandas as pd
import requests
from flask import Flask, jsonify, render_template_string, request

warnings.filterwarnings("ignore")

app = Flask(__name__)

# 配置 Telegram Bot
BOT_TOKEN = os.environ.get(
    "BOT_TOKEN", "8154088150:AAFBiKBgFMbiGMcXPgBFdGxpIXGuY4ao_KQ"
)
CHAT_ID = os.environ.get("CHAT_ID", "-1004291395114")

UPLOAD_FOLDER = "uploads"
HISTORY_FILE = "sent_history.json"
CANCEL_FILE = "cancel_signal.flag"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ---------------------------------------------------------
# 工具函数：消息历史持久化（解决多进程内存隔离问题）
# ---------------------------------------------------------
def load_sent_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []


def save_sent_history(records):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving history: {e}")


def record_sent_message(chat_id, message_id, group_id):
    records = load_sent_history()
    records.append(
        {"chat_id": chat_id, "message_id": message_id, "group_id": group_id}
    )
    save_sent_history(records)


def clear_sent_history():
    if os.path.exists(HISTORY_FILE):
        try:
            os.remove(HISTORY_FILE)
        except:
            pass


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>多云余额管理与播报系统 (SaaS Web 版)</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-100 min-h-screen p-8 font-sans">
    <div class="max-w-4xl mx-auto bg-white rounded-xl shadow-lg p-6">
        <header class="border-b pb-4 mb-6 flex justify-between items-center">
            <div>
                <h1 class="text-2xl font-bold text-slate-800">多云余额自动化管理控制台</h1>
                <p class="text-sm text-slate-500 mt-1">云端轻量级 Web App | 动态归集与 100% 物理撤回</p>
            </div>
            <span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800">
                🟢 云端服务运行中
            </span>
        </header>

        <!-- 文件上传区域 -->
        <div class="mb-6 border-2 border-dashed border-indigo-200 rounded-xl p-6 bg-indigo-50/50 text-center">
            <h3 class="text-indigo-900 font-semibold mb-2">📁 上传今日账单/列表文件 (支持多选 CSV / XLSX)</h3>
            <input type="file" id="fileInput" multiple accept=".csv, .xlsx" class="hidden" onchange="handleFileSelect(event)">
            <button onclick="document.getElementById('fileInput').click()" class="bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-2 px-5 rounded-lg transition text-sm shadow">
                选择并上传最新账单文件
            </button>
            <p id="fileCount" class="text-xs text-indigo-600 mt-2">支持多选 CSV / XLSX 同时上传（系统将自动智能归集同群账号）</p>
        </div>

        <!-- 操作控制按钮组 -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <button id="sendBtn" onclick="triggerBroadcast()" class="bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-3 px-4 rounded-lg transition flex items-center justify-center gap-2 shadow">
                🚀 一键全量播报
            </button>
            <button id="stopBtn" onclick="stopBroadcast()" class="bg-amber-500 hover:bg-amber-600 text-white font-medium py-3 px-4 rounded-lg transition flex items-center justify-center gap-2 shadow">
                ⏹️ 马上停止发送
            </button>
            <button id="recallBtn" onclick="recallBroadcast()" class="bg-rose-600 hover:bg-rose-700 text-white font-medium py-3 px-4 rounded-lg transition flex items-center justify-center gap-2 shadow">
                ↩️ 一键撤回已发消息
            </button>
        </div>

        <!-- 实时日志输出框 -->
        <div class="border rounded-lg p-4 bg-slate-900 text-slate-100 font-mono text-sm min-h-[280px] max-h-[480px] overflow-y-auto" id="logBox">
            <p class="text-slate-400">> 云端系统已就绪，请上传账单文件...</p>
        </div>
    </div>

    <script>
        function log(msg, color='text-slate-200') {
            const box = document.getElementById('logBox');
            box.innerHTML += `<p class="${color} mt-1">> ${msg}</p>`;
            box.scrollTop = box.scrollHeight;
        }

        async function handleFileSelect(event) {
            const files = event.target.files;
            if (files.length === 0) return;

            document.getElementById('fileCount').innerText = `已选择 ${files.length} 个文件，正在上传...`;
            const formData = new FormData();
            for (let i = 0; i < files.length; i++) {
                formData.append('files', files[i]);
            }

            try {
                const res = await fetch('/api/upload', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.success) {
                    log(`✅ 成功上传并更新了 ${data.uploaded_count} 个账单文件！`, 'text-emerald-400');
                    document.getElementById('fileCount').innerText = `已成功接收 ${data.uploaded_count} 个最新数据文件。`;
                } else {
                    log(`❌ 上传失败: ${data.error}`, 'text-rose-400');
                }
            } catch (err) {
                log(`❌ 上传异常: ${err.message}`, 'text-rose-400');
            }
        }

        async function triggerBroadcast() {
            log('正在解析最新数据并生成全量 Telegram 报表...', 'text-yellow-400');

            try {
                const res = await fetch('/api/broadcast', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    log(`🎉 播报完成！共成功推送了 ${data.total_groups} 个群组。`, 'text-emerald-400');
                    data.logs.forEach(l => log(l));
                } else {
                    log(`❌ 播报中止/失败: ${data.error}`, 'text-rose-400');
                    if (data.logs) data.logs.forEach(l => log(l));
                }
            } catch (err) {
                log(`❌ 请求异常: ${err.message}`, 'text-rose-400');
            }
        }

        async function stopBroadcast() {
            log('⚠️ 正在向后台发送中断标志...', 'text-amber-400');
            try {
                const res = await fetch('/api/stop', { method: 'POST' });
                const data = await res.json();
                log(data.message, 'text-amber-300');
            } catch (err) {
                log(`❌ 停止请求失败: ${err.message}`, 'text-rose-400');
            }
        }

        async function recallBroadcast() {
            if (!confirm('确定要彻底撤回刚才已发送的所有 Telegram 消息吗？')) return;
            log('🔄 正在请求后台批量撤回群组消息...', 'text-rose-300');
            try {
                const res = await fetch('/api/recall', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    log(`🚀 撤回指令已下达！后台正在逐条物理删除 ${data.target_count} 条已发消息...`, 'text-emerald-400');
                } else {
                    log(`❌ 撤回失败: ${data.error}`, 'text-rose-400');
                }
            } catch (err) {
                log(`❌ 撤回请求异常: ${err.message}`, 'text-rose-400');
            }
        }
    </script>
</body>
</html>
"""


def parse_tag(tag_str):
    if pd.isna(tag_str):
        return None
    s = str(tag_str).strip()
    if s.startswith("DJ-"):
        s = s[3:]
    elif s.startswith("DJ"):
        s = s[2:]
    parts = s.split("-")
    gid = parts[0].strip()
    if gid.startswith("C") and len(gid) >= 5:
        return gid
    return None


def clean_num(val):
    if pd.isna(val):
        return 0.0
    s = str(val).replace("$", "").replace(",", "").replace("'", "").strip()
    try:
        return float(s)
    except:
        return 0.0


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/upload", methods=["POST"])
def upload_files():
    try:
        uploaded_files = request.files.getlist("files")
        count = 0
        for file in uploaded_files:
            if file.filename:
                file_path = os.path.join(UPLOAD_FOLDER, file.filename)
                file.save(file_path)
                count += 1
        return jsonify({"success": True, "uploaded_count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/stop", methods=["POST"])
def stop_api():
    # 写入中断标志文件，所有进程可见
    with open(CANCEL_FILE, "w") as f:
        f.write("cancel")
    return jsonify(
        {"success": True, "message": "🛑 已触发全局中断指令，正在停止发送..."}
    )


# 异步线程执行消息撤回
def async_recall_task(records):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
    for item in records:
        try:
            payload = {
                "chat_id": item["chat_id"],
                "message_id": item["message_id"],
            }
            requests.post(url, json=payload, timeout=5)
            time.sleep(0.15)
        except Exception as e:
            print(f"Recall error for msg {item.get('message_id')}: {e}")
    # 删除完毕后清空历史记录
    clear_sent_history()


@app.route("/api/recall", methods=["POST"])
def recall_api():
    records = load_sent_history()
    if not records:
        return jsonify(
            {
                "success": False,
                "error": "没有找到可撤回的消息记录（可能尚未播报，或已经撤回过了）。",
            }
        )

    # 启动后台线程异步物理删除
    t = threading.Thread(target=async_recall_task, args=(records,))
    t.start()

    return jsonify({"success": True, "target_count": len(records)})


@app.route("/api/broadcast", methods=["POST"])
def broadcast_api():
    # 开始前清理中断标志
    if os.path.exists(CANCEL_FILE):
        try:
            os.remove(CANCEL_FILE)
        except:
            pass

    # 重置并清空上一次的历史记录
    clear_sent_history()

    try:
        all_data = []
        group_map = {}

        # 尝试读取模板名称，读取失败也完全不影响主逻辑
        template_files = glob.glob(os.path.join(UPLOAD_FOLDER, "*余额模板*.xlsx"))
        if template_files:
            try:
                groupcn = pd.read_excel(
                    template_files[0], sheet_name="groupcn", engine="openpyxl"
                )
                group_map = dict(
                    zip(
                        groupcn["groupID"].astype(str).str.strip(),
                        groupcn["chname"].astype(str).str.strip(),
                    )
                )
            except:
                pass

        all_uploaded = glob.glob(os.path.join(UPLOAD_FOLDER, "*"))

        for f in all_uploaded:
            filename = os.path.basename(f)

            # 1. 阿里云 CSV & UID 表
            if "阿里云" in filename and filename.endswith(".csv"):
                df = pd.read_csv(f)
                if "剩余额度" in df.columns and "备注" in df.columns:
                    df["balance"] = df["剩余额度"].apply(clean_num)
                    df["groupID"] = df["备注"].apply(parse_tag)
                    df_valid = df[
                        df["groupID"].notna() & (df["balance"] > 0)
                    ].copy()
                    for _, r in df_valid.iterrows():
                        tag = str(r["备注"])
                        c_type = (
                            "阿里合同号余额"
                            if any(
                                k in tag
                                for k in [
                                    "60",
                                    "65",
                                    "63",
                                    "70",
                                    "zhongdong",
                                    "lamei",
                                    "malai",
                                ]
                            )
                            else "阿里余额"
                        )
                        all_data.append(
                            {
                                "account": str(
                                    r.get("邮箱", r.get("账户ID", ""))
                                ).strip(),
                                "balance": r["balance"],
                                "groupID": r["groupID"],
                                "usage": 0.0,
                                "cloud_type": c_type,
                            }
                        )

            elif "uidlist" in filename and filename.endswith(".xlsx"):
                df = pd.read_excel(f, engine="openpyxl")
                if "可消费额度" in df.columns and "客户经理" in df.columns:
                    df["balance"] = df["可消费额度"].apply(clean_num)
                    df["groupID"] = df["客户经理"].apply(parse_tag)
                    df_valid = df[
                        df["groupID"].notna() & (df["balance"] > 0)
                    ].copy()
                    for _, r in df_valid.iterrows():
                        tag = str(r["客户经理"])
                        c_type = (
                            "阿里合同号余额"
                            if any(k in tag for k in ["60", "65", "63", "70"])
                            else "阿里余额"
                        )
                        all_data.append(
                            {
                                "account": str(r["客户账号"]).strip(),
                                "balance": r["balance"],
                                "groupID": r["groupID"],
                                "usage": 0.0,
                                "cloud_type": c_type,
                            }
                        )

            # 2. 腾讯云
            elif "腾讯云" in filename and filename.endswith(".csv"):
                tx_df = pd.read_csv(f)
                if "余额" in tx_df.columns and "备注" in tx_df.columns:
                    tx_df["balance"] = tx_df["余额"].apply(clean_num)
                    tx_df["groupID"] = tx_df["备注"].apply(parse_tag)
                    tx_valid = tx_df[
                        tx_df["groupID"].notna() & (tx_df["balance"] > 0)
                    ].copy()
                    for _, r in tx_valid.iterrows():
                        all_data.append(
                            {
                                "account": str(
                                    r.get("邮箱", r.get("账号", ""))
                                ).strip(),
                                "balance": r["balance"],
                                "groupID": r["groupID"],
                                "usage": 0.0,
                                "cloud_type": "腾讯余额",
                            }
                        )

            # 3. AWS CSV
            elif "AWS" in filename and filename.endswith(".csv"):
                df = pd.read_csv(f)
                if "可用额度" in df.columns and "备注" in df.columns:
                    df["balance"] = df["可用额度"].apply(clean_num)
                    df["usage"] = (
                        df["累计消费"].apply(clean_num)
                        if "累计消费" in df.columns
                        else 0.0
                    )
                    df["groupID"] = df["备注"].apply(parse_tag)
                    df_valid = df[
                        df["groupID"].notna()
                        & (df["状态"].astype(str).str.contains("使用中"))
                    ].copy()
                    for _, r in df_valid.iterrows():
                        acc = (
                            str(r["邮箱"]).strip()
                            if ("邮箱" in r and pd.notna(r["邮箱"]))
                            else str(r["账户ID"]).strip()
                        )
                        all_data.append(
                            {
                                "account": acc,
                                "balance": r["balance"],
                                "groupID": r["groupID"],
                                "usage": r["usage"],
                                "cloud_type": "AWS余额",
                            }
                        )

        if not all_data:
            return jsonify(
                {
                    "success": False,
                    "error": "未能解析到有效数据，请检查上传的文件文件名与格式！",
                }
            )

        # 绝对归集去重
        full_df = pd.DataFrame(all_data).drop_duplicates(
            subset=["account", "cloud_type", "groupID"]
        )
        cloud_order = [
            "腾讯余额",
            "阿里余额",
            "阿里合同号余额",
            "华为余额",
            "AWS余额",
            "GCP余额",
        ]
        all_gids = sorted(full_df["groupID"].unique())

        logs = []
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        for gid in all_gids:
            # 检查是否有中断标志文件
            if os.path.exists(CANCEL_FILE):
                logs.append("⚠️ 收到【停止发送】指令，播报任务已中止！")
                break

            grp = full_df[full_df["groupID"] == gid]
            chname = group_map.get(gid, "")
            header = f"{gid}（{chname}）" if chname else f"{gid}"
            msg_lines = [header, ""]

            for cloud in cloud_order:
                sub = grp[grp["cloud_type"] == cloud].copy()
                if sub.empty:
                    continue
                msg_lines.append(f"\n{cloud}")

                if cloud in ["AWS余额", "GCP余额"]:
                    sub = sub.sort_values(by="balance", ascending=True)
                    max_acc_len = max(
                        sub["account"].astype(str).str.len().max(), 8
                    )
                    col1_w = max_acc_len + 3
                    col2_w, col3_w = 12, 12

                    msg_lines.append("```")
                    msg_lines.append(
                        f"{'账号ID':<{col1_w - 2}} {'消费':>{col2_w}} {'余额':>{col3_w}}"
                    )
                    for _, r in sub.iterrows():
                        row_str = f"{str(r['account']):<{col1_w}} {float(r['usage']):>{col2_w}.2f} {float(r['balance']):>{col3_w}.2f}"
                        msg_lines.append(row_str)
                    msg_lines.append("```")
                else:
                    sub = sub.sort_values(by="balance", ascending=True)
                    msg_lines.append("邮箱\t可分配信用额度")
                    for _, r in sub.iterrows():
                        msg_lines.append(
                            f"{str(r['account'])}\t{float(r['balance']):.2f}"
                        )

            payload = {
                "chat_id": CHAT_ID,
                "text": "\n".join(msg_lines),
                "parse_mode": "Markdown",
            }
            res = requests.post(url, json=payload).json()
            if res.get("ok"):
                msg_id = res["result"]["message_id"]
                # 实时写入 JSON 硬盘文件
                record_sent_message(CHAT_ID, msg_id, gid)
                logs.append(f"群组 {gid} 推送成功！")
            else:
                logs.append(f"群组 {gid} 推送失败：{res.get('description')}")
            time.sleep(0.3)

        return jsonify(
            {"success": True, "total_groups": len(all_gids), "logs": logs}
        )
    except Exception as e:
        err_msg = traceback.format_exc()
        print(f"Error: {err_msg}")
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
