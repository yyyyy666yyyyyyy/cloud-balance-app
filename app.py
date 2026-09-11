import glob
import os
import time
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
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 网页 HTML 视图
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>多云余额管理与播报系统 (云端 Web 版)</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-100 min-h-screen p-8 font-sans">
    <div class="max-w-4xl mx-auto bg-white rounded-xl shadow-lg p-6">
        <header class="border-b pb-4 mb-6 flex justify-between items-center">
            <div>
                <h1 class="text-2xl font-bold text-slate-800">多云余额自动化管理控制台</h1>
                <p class="text-sm text-slate-500 mt-1">云端轻量级 Web App | 拖拽上传与一键播报</p>
            </div>
            <span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800">
                🟢 云端服务正常运行
            </span>
        </header>

        <!-- 拖拽上传文件区域 -->
        <div class="mb-6 border-2 border-dashed border-indigo-200 rounded-xl p-6 bg-indigo-50/50 text-center">
            <h3 class="text-indigo-900 font-semibold mb-2">📁 第一步：上传今日账单/列表文件 (支持多选 CSV / XLSX)</h3>
            <input type="file" id="fileInput" multiple accept=".csv, .xlsx" class="hidden" onchange="handleFileSelect(event)">
            <button onclick="document.getElementById('fileInput').click()" class="bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-2 px-5 rounded-lg transition text-sm">
                选择并上传最新账单文件
            </button>
            <p id="fileCount" class="text-xs text-indigo-600 mt-2">未选择文件（支持多个 CSV / XLSX 同时上传）</p>
        </div>

        <!-- 一键播报按钮 -->
        <div class="flex gap-4 mb-6">
            <button id="sendBtn" onclick="triggerBroadcast()" class="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-3 px-6 rounded-lg transition duration-200 flex items-center justify-center gap-2 shadow">
                🚀 第二步：解析并一键全量播报至 Telegram
            </button>
        </div>

        <!-- 实时日志显示框 -->
        <div class="border rounded-lg p-4 bg-slate-900 text-slate-100 font-mono text-sm min-h-[250px] max-h-[450px] overflow-y-auto" id="logBox">
            <p class="text-slate-400">> 云端系统已就绪，请上传最新的账单文件...</p>
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
            const btn = document.getElementById('sendBtn');
            btn.disabled = true;
            btn.classList.add('opacity-50', 'cursor-not-allowed');
            log('正在解析最新数据并生成 Telegram 报表...', 'text-yellow-400');

            try {
                const res = await fetch('/api/broadcast', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    log(`🎉 全量播报完成！共推送了 ${data.total_groups} 个群组。`, 'text-emerald-400');
                    data.logs.forEach(l => log(l));
                } else {
                    log(`❌ 播报失败: ${data.error}`, 'text-rose-400');
                }
            } catch (err) {
                log(`❌ 请求异常: ${err.message}`, 'text-rose-400');
            } finally {
                btn.disabled = false;
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
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


@app.route("/api/broadcast", methods=["POST"])
def broadcast_api():
    try:
        all_data = []

        # 读取上传的文件
        all_uploaded = glob.glob(os.path.join(UPLOAD_FOLDER, "*"))

        # 1. 处理阿里 CSV & 明细表
        for f in all_uploaded:
            filename = os.path.basename(f)
            if "阿里云" in filename and filename.endswith(".csv"):
                df = pd.read_csv(f)
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
                            "account": str(r["邮箱"]).strip(),
                            "balance": r["balance"],
                            "groupID": r["groupID"],
                            "usage": 0.0,
                            "cloud_type": c_type,
                        }
                    )

            elif "uidlist" in filename and filename.endswith(".xlsx"):
                df = pd.read_excel(f, engine="openpyxl")
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

            elif "腾讯云" in filename and filename.endswith(".csv"):
                tx_df = pd.read_csv(f)
                tx_df["balance"] = tx_df["余额"].apply(clean_num)
                tx_df["groupID"] = tx_df["备注"].apply(parse_tag)
                tx_valid = tx_df[
                    tx_df["groupID"].notna() & (tx_df["balance"] > 0)
                ].copy()
                for _, r in tx_valid.iterrows():
                    all_data.append(
                        {
                            "account": str(r["邮箱"]).strip(),
                            "balance": r["balance"],
                            "groupID": r["groupID"],
                            "usage": 0.0,
                            "cloud_type": "腾讯余额",
                        }
                    )

            elif "AWS" in filename and filename.endswith(".csv"):
                df = pd.read_csv(f)
                df["balance"] = df["可用额度"].apply(clean_num)
                df["usage"] = df["累计消费"].apply(clean_num)
                df["groupID"] = df["备注"].apply(parse_tag)
                df_valid = df[
                    df["groupID"].notna()
                    & (df["状态"].astype(str).str.contains("使用中"))
                ].copy()
                for _, r in df_valid.iterrows():
                    acc = (
                        str(r["邮箱"]).strip()
                        if pd.notna(r["邮箱"])
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
                    "error": "还没有上传任何有效的账单/列表文件！请先上传文件。",
                }
            )

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
            grp = full_df[full_df["groupID"] == gid]
            header = f"{gid}"
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
                logs.append(f"群组 {gid} 推送成功！")
            else:
                logs.append(f"群组 {gid} 推送失败：{res.get('description')}")
            time.sleep(0.3)

        return jsonify(
            {"success": True, "total_groups": len(all_gids), "logs": logs}
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
