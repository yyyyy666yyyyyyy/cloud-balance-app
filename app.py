import glob
import json
import os
import re
import threading
import time
import traceback
import warnings
import pandas as pd
import requests
from flask import Flask, jsonify, render_template_string, request

warnings.filterwarnings("ignore")

app = Flask(__name__)

BOT_TOKEN = os.environ.get(
    "BOT_TOKEN", "8154088150:AAFBiKBgFMbiGMcXPgBFdGxpIXGuY4ao_KQ"
)
CHAT_ID = os.environ.get("CHAT_ID", "-1004291395114")

UPLOAD_FOLDER = "uploads"
HISTORY_FILE = "sent_history.json"
CANCEL_FILE = "cancel_signal.flag"
HUAWEI_DICT_FILE = "huawei_dict.json"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ---------------------------------------------------------
# 持久化工具函数
# ---------------------------------------------------------
def load_huawei_dict():
    if os.path.exists(HUAWEI_DICT_FILE):
        try:
            with open(HUAWEI_DICT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_huawei_dict(dictionary):
    try:
        with open(HUAWEI_DICT_FILE, "w", encoding="utf-8") as f:
            json.dump(dictionary, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving huawei dict: {e}")


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


# 深度解析华为乱序多行文本
def parse_huawei_multiline_text(raw_text):
    hw_dict = load_huawei_dict()
    parsed_results = []

    # 按客户数据块切割（以 H****D 或 hid_ 为锚点）
    blocks = re.split(r"(?=hid_)", raw_text)

    for block in blocks:
        if not block.strip() or "hid_" not in block:
            continue

        # 1. 提取 HID
        hid_match = re.search(r"(hid_[a-zA-Z0-9_]+)", block)
        if not hid_match:
            continue
        hid = hid_match.group(1)

        # 2. 提取百分比使用率 (如 30.02% 或 0%)
        rate_match = re.search(r"(\d+(?:\.\d+)?)\s*%", block)
        usage_rate = float(rate_match.group(1)) / 100.0 if rate_match else 0.0

        # 3. 提取所有浮点数/数字，筛选一次性预算 (紧接着百分比前面的数字，或者最大的合理数值)
        numbers = re.findall(r"[\d,]+\.\d{2}", block)
        budget = 0.0
        if numbers:
            budget = max([clean_num(n) for n in numbers])

        # 4. 提取标签 (如 C00897-CDN, C01006-NICK)
        tag_match = re.search(r"(C\d{4,5}[-\w]*)", block)
        tag = tag_match.group(1) if tag_match else ""
        gid = parse_tag(tag) if tag else None

        # 映射邮箱与计算余额
        email = hw_dict.get(hid, hid)
        calc_balance = budget * (1.0 - usage_rate) if usage_rate <= 1.0 else 0.0

        parsed_results.append(
            {
                "hid": hid,
                "email": email,
                "budget": budget,
                "rate_percent": f"{usage_rate * 100:.2f}%",
                "balance": round(calc_balance, 2),
                "tag": tag,
                "groupID": gid or "未识别",
            }
        )

    return parsed_results


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>多云余额管理控制台 (SaaS 版)</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-100 min-h-screen p-8 font-sans">
    <div class="max-w-5xl mx-auto bg-white rounded-xl shadow-lg p-6">
        <header class="border-b pb-4 mb-6 flex justify-between items-center">
            <div>
                <h1 class="text-2xl font-bold text-slate-800">多云余额自动化管理控制台</h1>
                <p class="text-sm text-slate-500 mt-1">云端轻量级 Web App | 华为数据解析预览与 Telegram 撤回</p>
            </div>
            <span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800">
                🟢 云端服务运行中
            </span>
        </header>

        <!-- 1. 常规文件上传区域 -->
        <div class="mb-6 border-2 border-dashed border-indigo-200 rounded-xl p-5 bg-indigo-50/40 text-center">
            <h3 class="text-indigo-900 font-semibold mb-1">📁 阿里云 / 腾讯云 / AWS 列表上传</h3>
            <input type="file" id="fileInput" multiple accept=".csv, .xlsx" class="hidden" onchange="handleFileSelect(event)">
            <button onclick="document.getElementById('fileInput').click()" class="bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-2 px-5 rounded-lg transition text-sm shadow">
                选择并上传 CSV / XLSX 文件
            </button>
            <p id="fileCount" class="text-xs text-indigo-600 mt-2">支持多选 CSV / XLSX 同时上传</p>
        </div>

        <!-- 2. 华为云专用粘贴 & 映射预览专区 -->
        <div class="mb-6 border border-orange-200 rounded-xl p-5 bg-orange-50/30">
            <h3 class="text-orange-900 font-semibold mb-2 flex justify-between items-center">
                <span>⚡ 华为云专区（直接复制粘贴页面数据）</span>
                <button onclick="parseAndPreviewHuawei()" class="bg-orange-600 hover:bg-orange-700 text-white text-xs font-medium px-4 py-1.5 rounded transition shadow">
                    🔍 解析并预览华为数据
                </button>
            </h3>
            
            <textarea id="huaweiText" rows="4" placeholder="直接全选粘贴从华为拉取出来的整块错位数据..." class="w-full p-3 border rounded-lg font-mono text-xs text-slate-700 focus:ring-2 focus:ring-orange-400 focus:outline-none bg-white mb-3"></textarea>
            
            <!-- 华为解析预览表格 (默认隐藏，点击解析后展示) -->
            <div id="huaweiPreviewArea" class="hidden mb-4 border rounded-lg bg-white overflow-hidden shadow-sm">
                <div class="bg-orange-100 px-4 py-2 border-b flex justify-between items-center">
                    <span class="text-xs font-bold text-orange-900">📊 华为云解析结果人工核查 (发前预览)</span>
                    <span id="hwParsedCount" class="text-xs text-orange-700"></span>
                </div>
                <div class="max-h-60 overflow-y-auto">
                    <table class="w-full text-left text-xs">
                        <thead class="bg-slate-50 text-slate-600 border-b">
                            <tr>
                                <th class="p-2.5">HID</th>
                                <th class="p-2.5">映射邮箱/账号</th>
                                <th class="p-2.5">预算</th>
                                <th class="p-2.5">使用率</th>
                                <th class="p-2.5">自动算得余额</th>
                                <th class="p-2.5">提取 GroupID</th>
                            </tr>
                        </thead>
                        <tbody id="hwTableBody" class="divide-y text-slate-700"></tbody>
                    </table>
                </div>
            </div>

            <!-- 快速加新的 HID 字典映射 -->
            <div class="flex gap-2 items-center bg-white p-3 border rounded-lg">
                <span class="text-xs font-medium text-slate-600">➕ 补全未识别 HID 映射:</span>
                <input type="text" id="newHid" placeholder="HID (如 hid_xxx)" class="border rounded px-2 py-1 text-xs flex-1">
                <input type="text" id="newEmail" placeholder="真实邮箱 (如 user@abc.com)" class="border rounded px-2 py-1 text-xs flex-1">
                <button onclick="addHidMapping()" class="bg-orange-600 hover:bg-orange-700 text-white text-xs font-medium px-4 py-1.5 rounded transition">保存并更新预览</button>
            </div>
        </div>

        <!-- 3. 操作控制按钮组 -->
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

        <!-- 4. 实时日志输出框 -->
        <div class="border rounded-lg p-4 bg-slate-900 text-slate-100 font-mono text-sm min-h-[240px] max-h-[440px] overflow-y-auto" id="logBox">
            <p class="text-slate-400">> 系统就绪，请上传文件或粘贴华为数据...</p>
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

        async function parseAndPreviewHuawei() {
            const text = document.getElementById('huaweiText').value;
            if (!text.trim()) {
                alert('请先将华为页面拉取到的表格数据粘贴进输入框！');
                return;
            }

            try {
                const res = await fetch('/api/huawei/parse', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ raw_text: text })
                });
                const data = await res.json();
                if (data.success) {
                    const tbody = document.getElementById('hwTableBody');
                    tbody.innerHTML = '';
                    data.results.forEach(r => {
                        const isUnknown = r.email.startsWith('hid_');
                        const emailHtml = isUnknown 
                            ? `<span class="text-rose-600 font-bold">${r.email} (未绑定)</span>`
                            : `<span class="text-emerald-700 font-medium">${r.email}</span>`;

                        tbody.innerHTML += `
                            <tr>
                                <td class="p-2.5 font-mono text-slate-500">${r.hid}</td>
                                <td class="p-2.5">${emailHtml}</td>
                                <td class="p-2.5 font-mono">$${r.budget}</td>
                                <td class="p-2.5 font-mono">${r.rate_percent}</td>
                                <td class="p-2.5 font-mono text-emerald-600 font-bold">$${r.balance}</td>
                                <td class="p-2.5"><span class="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded">${r.groupID}</span></td>
                            </tr>
                        `;
                    });

                    document.getElementById('hwParsedCount').innerText = `成功识别出 ${data.results.length} 条账号记录`;
                    document.getElementById('huaweiPreviewArea').classList.remove('hidden');
                    log(`✅ 华为数据解析完成！已生成下方 ${data.results.length} 条预览表格供核对。`, 'text-orange-300');
                } else {
                    log(`❌ 解析失败: ${data.error}`, 'text-rose-400');
                }
            } catch (err) {
                log(`❌ 请求异常: ${err.message}`, 'text-rose-400');
            }
        }

        async function addHidMapping() {
            const hid = document.getElementById('newHid').value.trim();
            const email = document.getElementById('newEmail').value.trim();
            if (!hid || !email) {
                alert('请同时输入 HID 和对应的真实邮箱！');
                return;
            }

            try {
                const res = await fetch('/api/huawei/dict', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ hid, email })
                });
                const data = await res.json();
                if (data.success) {
                    log(`✅ 华为映射添加成功: ${hid} ➔ ${email}`, 'text-orange-300');
                    document.getElementById('newHid').value = '';
                    document.getElementById('newEmail').value = '';
                    parseAndPreviewHuawei(); // 自动重新刷新表格
                } else {
                    log(`❌ 映射添加失败: ${data.error}`, 'text-rose-400');
                }
            } catch (err) {
                log(`❌ 请求异常: ${err.message}`, 'text-rose-400');
            }
        }

        async function triggerBroadcast() {
            log('正在解析最新数据并生成全量 Telegram 报表...', 'text-yellow-400');
            const huaweiRaw = document.getElementById('huaweiText').value;

            try {
                const res = await fetch('/api/broadcast', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ huawei_raw: huaweiRaw })
                });
                const data = await res.json();
                if (data.success) {
                    log(`🎉 播报完成！共成功推送了 ${data.total_groups} 个群组。`, 'text-emerald-400');
                    data.logs.forEach(l => log(l));
                } else {
                    log(`❌ 播报失败: ${data.error}`, 'text-rose-400');
                }
            } catch (err) {
                log(`❌ 请求异常: ${err.message}`, 'text-rose-400');
            }
        }

        async function stopBroadcast() {
            log('⚠️ 正在向后台发送中断指令...', 'text-amber-400');
            try {
                const res = await fetch('/api/stop', { method: 'POST' });
                const data = await res.json();
                log(data.message, 'text-amber-300');
            } catch (err) {
                log(`❌ 停止请求失败: ${err.message}`, 'text-rose-400');
            }
        }

        async function recallBroadcast() {
            if (!confirm('确定要撤回刚才发送的所有 Telegram 消息吗？')) return;
            log('🔄 正在请求后台物理撤回群组消息...', 'text-rose-300');
            try {
                const res = await fetch('/api/recall', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    log(`🚀 撤回指令已下达！后台正在删除 ${data.target_count} 条消息...`, 'text-emerald-400');
                } else {
                    log(`❌ 撤回失败: ${data.error}`, 'text-rose-400');
                }
            } catch (err) {
                log(`❌ 撤回异常: ${err.message}`, 'text-rose-400');
            }
        }
    </script>
</body>
</html>
"""


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


@app.route("/api/huawei/parse", methods=["POST"])
def huawei_parse_api():
    try:
        data = request.json or {}
        raw_text = data.get("raw_text", "")
        results = parse_huawei_multiline_text(raw_text)
        return jsonify({"success": True, "results": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/huawei/dict", methods=["POST"])
def add_huawei_dict():
    try:
        data = request.json or {}
        hid = data.get("hid", "").strip()
        email = data.get("email", "").strip()
        if not hid or not email:
            return jsonify(
                {"success": False, "error": "HID 或邮箱不能为空！"}
            )

        dictionary = load_huawei_dict()
        dictionary[hid] = email
        save_huawei_dict(dictionary)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/stop", methods=["POST"])
def stop_api():
    with open(CANCEL_FILE, "w") as f:
        f.write("cancel")
    return jsonify(
        {"success": True, "message": "🛑 已触发全局中断指令，正在停止发送..."}
    )


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
            print(f"Recall error: {e}")
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

    t = threading.Thread(target=async_recall_task, args=(records,))
    t.start()
    return jsonify({"success": True, "target_count": len(records)})


@app.route("/api/broadcast", methods=["POST"])
def broadcast_api():
    if os.path.exists(CANCEL_FILE):
        try:
            os.remove(CANCEL_FILE)
        except:
            pass

    clear_sent_history()

    try:
        req_data = request.json or {}
        huawei_raw_text = req_data.get("huawei_raw", "")

        all_data = []
        group_map = {}

        # 1. 深度处理华为复制粘贴文本
        if huawei_raw_text.strip():
            hw_results = parse_huawei_multiline_text(huawei_raw_text)
            for r in hw_results:
                if r["groupID"] != "未识别" and r["balance"] > 0:
                    all_data.append(
                        {
                            "account": r["email"],
                            "balance": r["balance"],
                            "groupID": r["groupID"],
                            "usage": 0.0,
                            "cloud_type": "华为余额",
                        }
                    )

        # 2. 处理常规上传的文件 (阿里、腾讯、AWS)
        all_uploaded = glob.glob(os.path.join(UPLOAD_FOLDER, "*"))
        for f in all_uploaded:
            filename = os.path.basename(f)

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
                    "error": "未能解析到任何有效数据，请检查上传的文件或粘贴的华为数据！",
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
