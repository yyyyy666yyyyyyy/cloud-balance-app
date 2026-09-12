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
from flask import Flask, Response, jsonify, render_template_string, request

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

    invalid_keywords = ["自定义标签", "测试", "hid", "添加", "设置预算"]
    if any(k in s for k in invalid_keywords):
        return None

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


def parse_huawei_multiline_text(raw_text, hw_dict):
    parsed_results = []
    blocks = re.split(r"(?=hid_)", raw_text)

    for block in blocks:
        if not block.strip() or "hid_" not in block:
            continue

        hid_match = re.search(r"(hid_[a-zA-Z0-9_-]+)", block)
        if not hid_match:
            continue
        hid = hid_match.group(1).strip()

        tag_match = re.search(r"(C\d{4,5}[-\w]*)", block)
        tag = tag_match.group(1) if tag_match else ""
        gid = parse_tag(tag) if tag else None

        if not gid:
            continue

        rate_match = re.search(r"(\d+(?:\.\d+)?)\s*%", block)
        usage_rate = float(rate_match.group(1)) / 100.0 if rate_match else 0.0

        numbers = re.findall(r"[\d,]+\.\d{2}", block)
        budget = 0.0
        if numbers:
            budget = max([clean_num(n) for n in numbers])

        calc_balance = budget * (1.0 - usage_rate) if usage_rate <= 1.0 else 0.0

        if round(calc_balance, 2) <= 0:
            continue

        email = hw_dict.get(hid, hid)

        parsed_results.append(
            {
                "hid": hid,
                "email": email,
                "budget": budget,
                "rate_percent": f"{usage_rate * 100:.2f}%",
                "balance": round(calc_balance, 2),
                "tag": tag,
                "groupID": gid,
            }
        )

    return parsed_results


JS_SCRIPT = """
function switchTab(tabName) {
    var tabs = ['dashboard', 'huawei', 'dictionary'];
    for (var i = 0; i < tabs.length; i++) {
        var t = tabs[i];
        var el = document.getElementById('tab-' + t);
        var btn = document.getElementById('nav-' + t);
        if (el) el.classList.add('hidden');
        if (btn) btn.className = "w-full flex items-center gap-3 px-4 py-3 text-sm font-medium rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition";
    }

    var activeEl = document.getElementById('tab-' + tabName);
    var activeBtn = document.getElementById('nav-' + tabName);
    if (activeEl) activeEl.classList.remove('hidden');
    if (activeBtn) activeBtn.className = "w-full flex items-center gap-3 px-4 py-3 text-sm font-medium rounded-lg bg-indigo-600 text-white transition";

    if (tabName === 'dictionary') {
        loadServerDict();
    }
}

function log(msg, color) {
    color = color || 'text-slate-200';
    var box = document.getElementById('logBox');
    if (box) {
        box.innerHTML += '<p class="' + color + ' mt-1">> ' + msg + '</p>';
        box.scrollTop = box.scrollHeight;
    }
}

function loadServerDict() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', '/api/huawei/dict/list', true);
    xhr.onload = function() {
        if (xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            if (data.success) {
                renderDictTable(data.dict);
            }
        }
    };
    xhr.send();
}

function renderDictTable(dict) {
    var tbody = document.getElementById('dictTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    var keys = Object.keys(dict || {});

    if (keys.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="p-4 text-center text-slate-400">No HID mapping data found. Please paste and import above.</td></tr>';
        return;
    }

    for (var i = 0; i < keys.length; i++) {
        var k = keys[i];
        var tr = document.createElement('tr');
        tr.innerHTML = '<td class="p-3 font-mono text-slate-600">' + k + '</td>' +
            '<td class="p-3 font-medium text-emerald-700">' + dict[k] + '</td>' +
            '<td class="p-3 text-right"><button onclick="deleteDictKey(\'' + k + '\')" class="text-rose-500 hover:text-rose-700"><i class="fa-solid fa-trash"></i></button></td>';
        tbody.appendChild(tr);
    }
}

function importBatchDict() {
    var text = document.getElementById('batchDictText').value;
    if (!text || !text.trim()) {
        alert('Please paste table data containing HID and Email!');
        return;
    }

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/huawei/dict/import', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function() {
        if (xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            if (data.success) {
                document.getElementById('batchDictText').value = '';
                renderDictTable(data.dict);
                alert('Successfully saved ' + data.count + ' HID mappings!');
            } else {
                alert('Save failed: ' + data.error);
            }
        }
    };
    xhr.send(JSON.stringify({ raw_text: text }));
}

function deleteDictKey(key) {
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/huawei/dict/delete', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function() {
        if (xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            if (data.success) { renderDictTable(data.dict); }
        }
    };
    xhr.send(JSON.stringify({ key: key }));
}

function clearAllDict() {
    if (confirm('Are you sure you want to clear all HID dictionary mappings?')) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/huawei/dict/clear', true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                var data = JSON.parse(xhr.responseText);
                if (data.success) { renderDictTable({}); }
            }
        };
        xhr.send();
    }
}

function handleFileSelect(event) {
    var files = event.target.files;
    if (files.length === 0) return;

    document.getElementById('fileCount').innerText = 'Selected ' + files.length + ' files, uploading...';
    var formData = new FormData();
    for (var i = 0; i < files.length; i++) {
        formData.append('files', files[i]);
    }

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload', true);
    xhr.onload = function() {
        if (xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            if (data.success) {
                log('Uploaded ' + data.uploaded_count + ' bill files!', 'text-emerald-400');
                document.getElementById('fileCount').innerText = 'Successfully received ' + data.uploaded_count + ' files.';
            } else {
                log('Upload failed: ' + data.error, 'text-rose-400');
            }
        }
    };
    xhr.send(formData);
}

function parseAndPreviewHuawei() {
    var text = document.getElementById('huaweiText').value;
    if (!text.trim()) {
        alert('Please paste Huawei data into the text box first!');
        return;
    }

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/huawei/parse', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function() {
        if (xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            if (data.success) {
                var tbody = document.getElementById('hwTableBody');
                tbody.innerHTML = '';
                for (var i = 0; i < data.results.length; i++) {
                    var r = data.results[i];
                    var isUnknown = r.email.indexOf('hid_') !== -1;
                    var emailHtml = isUnknown 
                        ? '<span class="text-rose-600 font-bold">' + r.email + ' (Unbound)</span>'
                        : '<span class="text-emerald-700 font-medium">' + r.email + '</span>';

                    var tr = document.createElement('tr');
                    tr.innerHTML = '<td class="p-3 font-mono text-slate-500">' + r.hid + '</td>' +
                        '<td class="p-3">' + emailHtml + '</td>' +
                        '<td class="p-3 font-mono">$' + r.budget + '</td>' +
                        '<td class="p-3 font-mono">' + r.rate_percent + '</td>' +
                        '<td class="p-3 font-mono text-emerald-600 font-bold">$' + r.balance + '</td>' +
                        '<td class="p-3"><span class="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded font-semibold">' + r.groupID + '</span></td>';
                    tbody.appendChild(tr);
                }

                document.getElementById('hwParsedCount').innerText = 'Extracted ' + data.results.length + ' valid records';
                document.getElementById('huaweiPreviewArea').classList.remove('hidden');
                log('Huawei parsing complete! Filtered invalid tags and 0 balance records, ' + data.results.length + ' valid records remaining.', 'text-orange-300');
            } else {
                log('Parse failed: ' + data.error, 'text-rose-400');
            }
        }
    };
    xhr.send(JSON.stringify({ raw_text: text }));
}

function triggerBroadcast() {
    log('Parsing data and sending Telegram broadcast...', 'text-yellow-400');
    var huaweiRaw = document.getElementById('huaweiText').value;

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/broadcast', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function() {
        if (xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            if (data.success) {
                log('Broadcast complete! Successfully sent to ' + data.total_groups + ' groups.', 'text-emerald-400');
                if (data.logs) {
                    for (var i = 0; i < data.logs.length; i++) { log(data.logs[i]); }
                }
            } else {
                log('Broadcast failed: ' + data.error, 'text-rose-400');
            }
        }
    };
    xhr.send(JSON.stringify({ huawei_raw: huaweiRaw }));
}

function stopBroadcast() {
    log('Sending stop command to server...', 'text-amber-400');
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/stop', true);
    xhr.onload = function() {
        if (xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            log(data.message, 'text-amber-300');
        }
    };
    xhr.send();
}

function recallBroadcast() {
    if (!confirm('Are you sure you want to recall all sent Telegram messages?')) return;
    log('Requesting server to recall messages...', 'text-rose-300');
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/recall', true);
    xhr.onload = function() {
        if (xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            if (data.success) {
                log('Recall command issued! Deleting ' + data.target_count + ' messages...', 'text-rose-400');
            } else {
                log('Recall failed: ' + data.error, 'text-rose-400');
            }
        }
    };
    xhr.send();
}
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>多云余额自动化管理控制台</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="/static/script.js"></script>
</head>
<body class="bg-slate-100 min-h-screen flex font-sans">

    <!-- 侧边栏导航 -->
    <aside class="w-64 bg-slate-900 text-slate-300 flex flex-col min-h-screen p-4 flex-shrink-0 shadow-xl">
        <div class="px-3 py-4 border-b border-slate-800 mb-6 flex items-center gap-3">
            <div class="bg-indigo-600 p-2 rounded-lg text-white font-bold"><i class="fa-solid fa-cloud"></i></div>
            <div>
                <h2 class="text-white font-bold text-base leading-tight">多云管理系统</h2>
                <p class="text-xs text-slate-500">SaaS Web 控制台</p>
            </div>
        </div>

        <nav class="space-y-1 flex-1">
            <button onclick="switchTab('dashboard')" id="nav-dashboard" class="w-full flex items-center gap-3 px-4 py-3 text-sm font-medium rounded-lg bg-indigo-600 text-white transition">
                <i class="fa-solid fa-gauge w-5"></i> 播报控制台
            </button>
            <button onclick="switchTab('huawei')" id="nav-huawei" class="w-full flex items-center gap-3 px-4 py-3 text-sm font-medium rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition">
                <i class="fa-solid fa-bolt text-orange-400 w-5"></i> 华为云专区
            </button>
            <button onclick="switchTab('dictionary')" id="nav-dictionary" class="w-full flex items-center gap-3 px-4 py-3 text-sm font-medium rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition">
                <i class="fa-solid fa-book w-5"></i> HID 映射字典
            </button>
        </nav>

        <div class="p-3 bg-slate-800/60 rounded-lg border border-slate-700/50 text-xs">
            <div class="flex items-center gap-2 text-emerald-400 mb-1 font-semibold">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span> 云端服务就绪
            </div>
            <p class="text-slate-400">Telegram Bot: 正常连线</p>
        </div>
    </aside>

    <!-- 主内容区 -->
    <main class="flex-1 p-8 overflow-y-auto">

        <!-- Tab 1: 播报控制台 -->
        <section id="tab-dashboard" class="space-y-6">
            <header class="bg-white p-6 rounded-xl shadow-sm border border-slate-200 flex justify-between items-center">
                <div>
                    <h1 class="text-2xl font-bold text-slate-800">全量播报控制台</h1>
                    <p class="text-sm text-slate-500 mt-1">支持多云列表文件上传与一键全量 Telegram 广播</p>
                </div>
            </header>

            <div class="border-2 border-dashed border-indigo-200 rounded-xl p-6 bg-indigo-50/40 text-center">
                <h3 class="text-indigo-900 font-semibold mb-2">📁 上传阿里云 / 腾讯云 / AWS 账单列表</h3>
                <input type="file" id="fileInput" multiple accept=".csv, .xlsx" class="hidden" onchange="handleFileSelect(event)">
                <button onclick="document.getElementById('fileInput').click()" class="bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-2 px-5 rounded-lg transition text-sm shadow">
                    选择上传 CSV / XLSX 文件
                </button>
                <p id="fileCount" class="text-xs text-indigo-600 mt-2">支持多选文件同时上传</p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <button id="sendBtn" onclick="triggerBroadcast()" class="bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-3.5 px-4 rounded-xl transition flex items-center justify-center gap-2 shadow-sm">
                    🚀 一键全量播报
                </button>
                <button id="stopBtn" onclick="stopBroadcast()" class="bg-amber-500 hover:bg-amber-600 text-white font-medium py-3.5 px-4 rounded-xl transition flex items-center justify-center gap-2 shadow-sm">
                    ⏹️ 马上停止发送
                </button>
                <button id="recallBtn" onclick="recallBroadcast()" class="bg-rose-600 hover:bg-rose-700 text-white font-medium py-3.5 px-4 rounded-xl transition flex items-center justify-center gap-2 shadow-sm">
                    ↩️ 一键撤回已发消息
                </button>
            </div>

            <div class="border rounded-xl p-4 bg-slate-900 text-slate-100 font-mono text-sm min-h-[300px] max-h-[500px] overflow-y-auto" id="logBox">
                <p class="text-slate-400">> 云端系统已就绪，请选择上传账单文件或在华为专区粘贴数据...</p>
            </div>
        </section>


        <!-- Tab 2: 华为云专区 -->
        <section id="tab-huawei" class="hidden space-y-6">
            <header class="bg-white p-6 rounded-xl shadow-sm border border-slate-200 flex justify-between items-center">
                <div>
                    <h1 class="text-2xl font-bold text-slate-800">华为云数据专区</h1>
                    <p class="text-sm text-slate-500 mt-1">粘贴华为原始文本，系统将自动清洗垃圾标签、智能计算余额</p>
                </div>
                <button onclick="parseAndPreviewHuawei()" class="bg-orange-600 hover:bg-orange-700 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition shadow">
                    🔍 解析并预览华为数据
                </button>
            </header>

            <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
                <textarea id="huaweiText" rows="6" placeholder="直接在此粘贴华为页面全选拉取的整块数据..." class="w-full p-4 border rounded-xl font-mono text-xs text-slate-700 focus:ring-2 focus:ring-orange-400 focus:outline-none bg-slate-50/50"></textarea>

                <div id="huaweiPreviewArea" class="hidden border rounded-xl bg-white overflow-hidden shadow-sm">
                    <div class="bg-orange-100 px-4 py-3 border-b flex justify-between items-center">
                        <span class="text-xs font-bold text-orange-900">📊 华为云解析有效数据 (已过滤非客户标签与0余额记录)</span>
                        <span id="hwParsedCount" class="text-xs text-orange-700 font-medium"></span>
                    </div>
                    <div class="max-h-80 overflow-y-auto">
                        <table class="w-full text-left text-xs">
                            <thead class="bg-slate-50 text-slate-600 border-b">
                                <tr>
                                    <th class="p-3">HID</th>
                                    <th class="p-3">映射邮箱/账号</th>
                                    <th class="p-3">一次性预算</th>
                                    <th class="p-3">使用率</th>
                                    <th class="p-3">算得余额</th>
                                    <th class="p-3">提取 GroupID</th>
                                </tr>
                            </thead>
                            <tbody id="hwTableBody" class="divide-y text-slate-700"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </section>


        <!-- Tab 3: HID 映射字典管理 -->
        <section id="tab-dictionary" class="hidden space-y-6">
            <header class="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                <h1 class="text-2xl font-bold text-slate-800">华为 HID 邮箱字典管理</h1>
                <p class="text-sm text-slate-500 mt-1">从 Excel 复制两列批量粘贴导入 HID 映射，直接存入云端</p>
            </header>

            <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
                <h3 class="font-bold text-slate-800 text-sm">📋 批量添加/导入 HID 映射 (从 Excel 复制两列直接粘贴):</h3>
                <textarea id="batchDictText" rows="6" placeholder="在这里直接粘贴包含 HID 和 邮箱 的两列数据..." class="w-full p-3 border rounded-xl font-mono text-xs focus:ring-2 focus:ring-indigo-400 focus:outline-none bg-slate-50/50"></textarea>
                <div class="flex justify-end">
                    <button onclick="importBatchDict()" class="bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium px-5 py-2.5 rounded-lg transition shadow">
                        批量保存映射
                    </button>
                </div>
            </div>

            <div class="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div class="p-4 border-b bg-slate-50 flex justify-between items-center">
                    <span class="font-bold text-slate-700 text-sm">已生效的 HID 映射字典列表</span>
                    <button onclick="clearAllDict()" class="text-xs text-rose-600 hover:underline">清空所有字典</button>
                </div>
                <div class="max-h-80 overflow-y-auto">
                    <table class="w-full text-left text-xs">
                        <thead class="bg-slate-100 text-slate-600 border-b">
                            <tr>
                                <th class="p-3">HID 标识</th>
                                <th class="p-3">映射真实邮箱</th>
                                <th class="p-3 text-right">操作</th>
                            </tr>
                        </thead>
                        <tbody id="dictTableBody" class="divide-y"></tbody>
                    </table>
                </div>
            </div>
        </section>

    </main>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


# 修复 Flask Response，移除引起 500 崩溃的 charset 参数！
@app.route("/static/script.js")
def serve_script():
    return Response(
        JS_SCRIPT, mimetype="application/javascript; charset=utf-8"
    )


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


@app.route("/api/huawei/dict/list", methods=["GET"])
def huawei_dict_list():
    return jsonify({"success": True, "dict": load_huawei_dict()})


@app.route("/api/huawei/dict/import", methods=["POST"])
def huawei_dict_import_api():
    try:
        data = request.json or {}
        raw_text = data.get("raw_text", "")
        lines = raw_text.strip().split("\n")

        current_dict = load_huawei_dict()
        added_count = 0

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            parts = re.split(r"[\s,\t]+", line_str)
            if len(parts) >= 2:
                hid_cand = parts[0].strip()
                email_cand = parts[1].strip()
                if "hid_" in hid_cand:
                    current_dict[hid_cand] = email_cand
                    added_count += 1

        save_huawei_dict(current_dict)
        return jsonify(
            {"success": True, "count": added_count, "dict": current_dict}
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/huawei/dict/delete", methods=["POST"])
def huawei_dict_delete_api():
    try:
        data = request.json or {}
        key = data.get("key", "").strip()
        current_dict = load_huawei_dict()
        if key in current_dict:
            del current_dict[key]
            save_huawei_dict(current_dict)
        return jsonify({"success": True, "dict": current_dict})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/huawei/dict/clear", methods=["POST"])
def huawei_dict_clear_api():
    save_huawei_dict({})
    return jsonify({"success": True})


@app.route("/api/huawei/parse", methods=["POST"])
def huawei_parse_api():
    try:
        data = request.json or {}
        raw_text = data.get("raw_text", "")
        hw_dict = load_huawei_dict()
        results = parse_huawei_multiline_text(raw_text, hw_dict)
        return jsonify({"success": True, "results": results})
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
        hw_dict = load_huawei_dict()

        all_data = []
        group_map = {}

        if huawei_raw_text.strip():
            hw_results = parse_huawei_multiline_text(huawei_raw_text, hw_dict)
            for r in hw_results:
                if r["groupID"] and r["balance"] > 0:
                    all_data.append(
                        {
                            "account": r["email"],
                            "balance": r["balance"],
                            "groupID": r["groupID"],
                            "usage": 0.0,
                            "cloud_type": "华为余额",
                        }
                    )

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
