import flet as ft

# Flet 버전 호환 처리
# 최신 Flet에서는 ft.colors가 ft.Colors로 변경되어 오류가 날 수 있습니다.
if not hasattr(ft, "colors") and hasattr(ft, "Colors"):
    ft.colors = ft.Colors

import firebase_admin
from firebase_admin import credentials, db
import os
from datetime import datetime
import time
import threading
import uuid
import json

# Firebase 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
key_path = os.path.join(current_dir, "firebase-key.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(key_path)
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://best-driver-f130f-default-rtdb.firebaseio.com/"
    })


def main(page: ft.Page):
    page.title = "순수익 순위표"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO
    page.window_width = 430
    page.window_height = 800
    def show_admin_unlock():
        admin_unlock_row.visible = True
        page.update()
    user_info = {"name": None}
    prev_ranks = {}

    ADMIN_PASSWORD = "1234"
    admin_mode = {"enabled": False}
    admin_press = {"start": None, "ready": False}
    # ---------- 공통 함수 ----------
    def get_today():
        return datetime.now().strftime("%Y-%m-%d")

    def get_month():
        return datetime.now().strftime("%Y-%m")

    def get_my_name():
        return user_info["name"] or ""

    def show_msg(message):
        alert = ft.AlertDialog(
            modal=True,
            title=ft.Text("알림"),
            content=ft.Text(message),
            actions=[
                ft.TextButton("확인", on_click=lambda e: close_alert(alert))
            ])

        if alert not in page.overlay:
            page.overlay.append(alert)

        alert.open = True
        page.update()

    def close_alert(alert):
        alert.open = False
        page.update()
        
    def safe_key(text):
        # Firebase 경로에 쓰면 안 되는 문자 제거
        if not text:
            return ""
        return (
            text.strip()
            .replace(".", "_")
            .replace("#", "_")
            .replace("$", "_")
            .replace("[", "_")
            .replace("]", "_")
            .replace("/", "_")
        )

    def update_date_text():
        now = datetime.now()
        date_text.value = f"📅 {now.month}월 {now.day}일"

    def get_device_id():
        """
        브라우저/휴대폰마다 다른 고유번호를 저장합니다.
        저장소 오류가 나도 unknown_device처럼 모두 같은 값으로 묶이지 않게 처리합니다.
        """
        storage_key = "driver_profit_device_id"

        try:
            device_id = page.client_storage.get(storage_key)

            if not device_id or device_id == "unknown_device":
                device_id = str(uuid.uuid4())
                page.client_storage.set(storage_key, device_id)

            return device_id

        except Exception:
        # 절대 unknown_device 같은 공통값을 쓰면 안 됨
            if not hasattr(page, "_fallback_device_id"):
                page._fallback_device_id = str(uuid.uuid4())
            return page._fallback_device_id

    def get_device_locked_nickname():
        device_id = get_device_id()
        device_data = db.reference(f"devices/{device_id}").get()

        if isinstance(device_data, dict):
            return device_data.get("nickname")

        # 예전 방식으로 devices/{device_id} = "닉네임" 저장된 경우도 대응
        if isinstance(device_data, str):
            return device_data

        return None

    def set_device_locked_nickname(name):
        device_id = get_device_id()
        db.reference(f"devices/{device_id}").set({
            "nickname": name,
            "locked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        set_saved_nickname(name)

    def is_blocked_user(name):
        # 닉네임 차단은 사용하지 않습니다.
        # 차단은 기기(device_id) 기준으로만 처리합니다.
        return False
    
    # ---------- 화면 ----------
    status_text = ft.Text("로그인 후 이용하세요")
    date_text = ft.Text("", size=14)
    info_text = ft.Text("※ 수익 입력 기준: 익일 오전 7시까지", size=12)
    rank_list = ft.ListView(expand=True, spacing=8, auto_scroll=False)
    
    profit_input = ft.TextField(
        label="오늘 순수익 입력",
        keyboard_type=ft.KeyboardType.NUMBER,
        disabled=True)

    record_btn = ft.ElevatedButton("기록하기", disabled=True)

    quick_buttons = ft.Row(
        wrap=True,
        controls=[
            ft.ElevatedButton("초기화", disabled=True),
            ft.ElevatedButton("+1만", disabled=True),
            ft.ElevatedButton("+5만", disabled=True),
            ft.ElevatedButton("+10만", disabled=True),
        ])

    admin_section = ft.Column(visible=False, scroll=ft.ScrollMode.AUTO, height=560)

    # ---------- 입력 포맷 ----------
    def format_number(e):
        raw = profit_input.value.replace(",", "").strip()
        if raw == "":
            return
        if not raw.isdigit():
            profit_input.value = ""
            profit_input.update()
            return
        profit_input.value = f"{int(raw):,}"
        profit_input.update()

    profit_input.on_change = format_number

    def add_amount(amount):
        raw = profit_input.value.replace(",", "").strip()
        current = int(raw) if raw.isdigit() else 0
        new_value = max(0, current + amount)
        profit_input.value = f"{new_value:,}" if new_value else ""
        profit_input.update()

    def clear_input(e=None):
        profit_input.value = ""
        profit_input.update()

    quick_buttons.controls[1].on_click = lambda e: add_amount(10000)
    quick_buttons.controls[2].on_click = lambda e: add_amount(50000)
    quick_buttons.controls[3].on_click = lambda e: add_amount(100000)
    quick_buttons.controls[0].on_click = clear_input

    def set_logged_in_ui():
        profit_input.disabled = False
        record_btn.disabled = False
        for b in quick_buttons.controls:
            b.disabled = False

        admin_section.visible = admin_mode["enabled"]

        # 로그인/승인 전에는 뒤 화면을 숨기고, 로그인 완료 후에만 메인 화면을 보여줍니다.
        try:
            app_content.visible = True
            pending_screen.visible = False
        except NameError:
            pass

        page.update()

    # ---------- 강제 차단 / 강제 로그아웃 ----------
    def is_current_user_blocked():
        """현재 접속자가 관리자에게 가입 차단되었는지 확인합니다.
        단, 관리자가 닉네임을 변경한 경우에는 차단이 아니라 새 닉네임으로 자동 전환합니다.
        """
        name = get_my_name()
        if not name:
            return False

        try:
            device_id = get_device_id()

            # 1) 기기 차단 목록에 있으면 즉시 차단
            if device_id and db.reference(f"blocked_devices/{device_id}").get() is not None:
                return True

            # 2) users에 현재 닉네임이 없으면 차단/삭제인지, 닉네임 변경인지 구분
            if db.reference(f"users/{name}").get() is None:
                device_data = db.reference(f"devices/{device_id}").get() if device_id else None
                linked_name = None

                if isinstance(device_data, dict):
                    linked_name = device_data.get("nickname")
                elif isinstance(device_data, str):
                    linked_name = device_data

                # A. devices/{현재기기}가 새 닉네임을 가리키면 닉네임 변경으로 처리
                if linked_name and linked_name != name and db.reference(f"users/{linked_name}").get() is not None:
                    page.pubsub.send_all(f"nickname_changed::{name}::{linked_name}")
                    return False

                # B. 혹시 devices 갱신이 늦었거나 누락돼도, users 전체에서 같은 device_id를 찾으면
                #    차단이 아니라 닉네임 변경으로 처리
                users_data = db.reference("users").get() or {}
                if device_id and isinstance(users_data, dict):
                    for candidate_name, candidate_data in users_data.items():
                        if not isinstance(candidate_data, dict):
                            continue
                        if candidate_name != name and candidate_data.get("device_id") == device_id:
                            page.pubsub.send_all(f"nickname_changed::{name}::{candidate_name}")
                            return False

                # C. 그래도 찾지 못할 때만 진짜 차단/삭제로 판단
                return True

        except Exception:
            # 네트워크 오류 등 임시 오류는 차단으로 처리하지 않음
            return False

        return False

    def force_logout_due_to_block(message="관리자에 의해 가입 차단되어 이용할 수 없습니다."):
        """차단된 사용자를 현재 화면에서 즉시 내보냅니다."""
        pending_login["checking"] = False
        admin_mode["enabled"] = False
        user_info["name"] = None

        profit_input.disabled = True
        record_btn.disabled = True
        for b in quick_buttons.controls:
            b.disabled = True

        admin_section.visible = False
        admin_unlock_row.visible = False

        try:
            page.client_storage.remove("saved_nickname")
        except Exception:
            pass

        try:
            login_dialog.open = False
            pending_screen.visible = False
            app_content.visible = False
            blocked_screen.visible = True
            blocked_text.value = f"🚫 {message}"
        except NameError:
            pass

        page.update()

    # ---------- 랭킹 ----------
    def render_ranking():
        nonlocal prev_ranks

        archive_previous_month_if_needed()
        month = get_month()
        data = db.reference(f"rankings/{month}").get() or {}
        users = db.reference("users").get() or {}

        # 기존 가입자 중 이번 달 랭킹에 없는 사람도 0원으로 표시
        for nickname in users.keys():
            if nickname not in data:
                data[nickname] = 0

        rank_list.controls.clear()
        current_ranks = {}

        if data:
            sorted_data = sorted(data.items(), key=lambda x: int(x[1] or 0), reverse=True)

            for i, (name, profit) in enumerate(sorted_data):
                rank = i + 1
                current_ranks[name] = rank

                if name in prev_ranks:
                    old_rank = prev_ranks[name]
                    if old_rank > rank:
                        change = "🔺"
                    elif old_rank < rank:
                        change = "🔻"
                    else:
                        change = "➖"
                else:
                    change = "🆕"

                medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else ""

                rank_list.controls.append(
                    ft.ListTile(
                        title=ft.Text(
                            f"{medal} {rank}위 {change} - {name}",
                            weight=ft.FontWeight.BOLD if name == get_my_name() else None),
                        subtitle=ft.Text(f"{int(profit):,}원"))
                )
        else:
            rank_list.controls.append(ft.Text("아직 이번 달 기록이 없습니다."))

        prev_ranks = current_ranks

        if get_my_name():
            daily_check = db.reference(f"daily/{month}/{get_my_name()}/{get_today()}").get()
            status_text.value = f"{get_my_name()}님 | " + ("✅ 오늘 입력 완료" if daily_check else "❌ 아직 입력 안함")
        else:
            status_text.value = "로그인 후 이용하세요"
            
        update_date_text()
        page.update()

    def on_message(msg):
        if msg == "refresh":
            render_ranking()
        elif isinstance(msg, str) and msg.startswith("approved_login::"):
            name = msg.split("::", 1)[1]
            user_ref = db.reference(f"users/{name}")
            if user_ref.get() is not None:
                login_success(name, user_ref)
        elif isinstance(msg, str) and msg.startswith("approval_rejected::"):
            pending_login["checking"] = False
            pending_hint_text.value = "가입 신청이 거절되었거나 삭제되었습니다. 관리자에게 문의하세요."
            page.update()
        elif isinstance(msg, str) and msg.startswith("force_logout::"):
            target = msg.split("::", 1)[1]
            if target == get_my_name():
                force_logout_due_to_block()
        elif isinstance(msg, str) and msg.startswith("nickname_changed::"):
            parts = msg.split("::")
            if len(parts) == 3:
                old_name, new_name = parts[1], parts[2]
                if old_name == get_my_name():
                    user_info["name"] = new_name
                    set_saved_nickname(new_name)
                    try:
                        blocked_screen.visible = False
                        pending_screen.visible = False
                        app_content.visible = True
                    except NameError:
                        pass
                    render_ranking()
                    show_msg(f"닉네임이 {new_name}(으)로 변경되었습니다.")

    page.pubsub.subscribe(on_message)

    # ---------- 오늘 입력 현황 ----------
    def show_today_status(e):
        month = get_month()
        today = get_today()

        users = db.reference("users").get() or {}
        daily = db.reference(f"daily/{month}").get() or {}

        lines = []
        for nickname in sorted(users.keys()):
            checked = False
            if isinstance(daily, dict):
                checked = nickname in daily and isinstance(daily.get(nickname), dict) and today in daily.get(nickname, {})
            mark = "✅ 입력완료" if checked else "❌ 미입력"
            lines.append(f"{nickname} - {mark}")

        show_msg("\n".join(lines) if lines else "가입된 기사가 없습니다.")

    # ---------- 이번 달 기사별 총액 보기 ----------
    def show_month_total(e):
        month = get_month()
        now = datetime.now()

        rankings = db.reference(f"rankings/{month}").get() or {}
        users = db.reference("users").get() or {}

        # 가입자는 기록이 없어도 0원으로 표시
        for nickname in users.keys():
            if nickname not in rankings:
                rankings[nickname] = 0

        if not rankings:
            show_msg("이번 달 기록이 없습니다.")
            return

        sorted_totals = sorted(
            rankings.items(),
            key=lambda x: int(x[1] or 0),
            reverse=True
        )

        lines = [f"📅 {now.month}월 기사별 총액", ""]

        for name, total in sorted_totals:
            lines.append(f"{name}  {int(total or 0):,}원")

        show_msg("\n".join(lines))


    # ---------- 지난달 기록 보관 / 보기 ----------
    def get_previous_month():
        now = datetime.now()
        year = now.year
        month = now.month - 1
        if month == 0:
            year -= 1
            month = 12
        return f"{year:04d}-{month:02d}"

    def archive_previous_month_if_needed():
        """지난달 rankings 데이터를 monthly_archives에 따로 보관합니다."""
        prev_month = get_previous_month()
        archive_ref = db.reference(f"monthly_archives/{prev_month}")

        # 이미 보관되어 있으면 다시 덮어쓰지 않음
        if archive_ref.get() is not None:
            return

        rankings = db.reference(f"rankings/{prev_month}").get() or {}
        if not rankings:
            return

        archive_ref.set({
            "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rankings": rankings,
        })

    def show_previous_month_total(e):
        archive_previous_month_if_needed()
        prev_month = get_previous_month()

        archive_data = db.reference(f"monthly_archives/{prev_month}").get() or {}
        rankings = archive_data.get("rankings") if isinstance(archive_data, dict) else {}

        # archive가 아직 없으면 기존 rankings에서도 한 번 더 확인
        if not rankings:
            rankings = db.reference(f"rankings/{prev_month}").get() or {}

        if not rankings:
            show_msg("지난달 기록이 없습니다.")
            return

        sorted_totals = sorted(
            rankings.items(),
            key=lambda x: int(x[1] or 0),
            reverse=True
        )

        lines = [f"📦 지난달 기록 ({prev_month})", ""]
        for i, (name, total) in enumerate(sorted_totals, start=1):
            lines.append(f"{i}위 - {name}  {int(total or 0):,}원")

        show_msg("\n".join(lines))

    # ---------- 수익 입력 ----------
    def update_profit(e):
        name = get_my_name()
        if not name:
            show_msg("먼저 로그인하세요.")
            return

        if is_current_user_blocked():
            force_logout_due_to_block()
            return

        today = get_today()
        month = today[:7]

        raw = profit_input.value.replace(",", "").strip()
        if not raw.isdigit():
            show_msg("금액을 숫자로 입력하세요.")
            return

        value = int(raw)

        if value <= 0:
            show_msg("0원은 입력할 수 없습니다.")
            return

        if value >= 1000000:
            show_msg("장난질하지마 손모가지 날아가붕게~")
            return

        daily_ref = db.reference(f"daily/{month}/{name}/{today}")

        if daily_ref.get() is not None:
            show_msg("오늘은 이미 입력했습니다. 수정은 관리자에게 요청하세요.")
            return

        # 월별 총합 기준으로 저장
        ranking_ref = db.reference(f"rankings/{month}/{name}")
        current_total = ranking_ref.get() or 0
        new_total = int(current_total) + value

        daily_ref.set({
            "profit": value,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        ranking_ref.set(new_total)

        # 사용자 정보에도 참고용 저장
        db.reference(f"users/{name}").update({
            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            f"monthly_total/{month}": new_total,
        })

        clear_input()
        render_ranking()
        page.pubsub.send_all("refresh")
        show_msg("오늘 순수익이 기록되었습니다.")

    record_btn.on_click = update_profit

    # ---------- 관리자 모드 ----------
    admin_unlock_pw_input = ft.TextField(
        label="관리자 비밀번호",
        password=True,
        can_reveal_password=True,
        width=220)

    def open_admin_mode(e):
        if not get_my_name():
            show_msg("먼저 로그인하세요.")
            return

        if admin_unlock_pw_input.value.strip() != ADMIN_PASSWORD:
            show_msg("관리자 비밀번호가 틀렸습니다.")
            return

        admin_mode["enabled"] = True
        admin_unlock_pw_input.value = ""
        admin_section.visible = True
        page.update()
        show_msg("관리자 모드가 열렸습니다.")

    def close_admin_mode(e):
        admin_mode["enabled"] = False
        admin_section.visible = False
        admin_unlock_row.visible = False   # ✅ 이게 핵심
        page.update()
        show_msg("관리자 모드가 닫혔습니다.")

    admin_unlock_row = ft.Row(
        visible=False,
        wrap=True,
        controls=[
            admin_unlock_pw_input,
            ft.ElevatedButton("관리자 모드 열기", on_click=open_admin_mode),
        ])

    # ---------- 관리자 ----------
    admin_name_input = ft.TextField(label="수정할 닉네임")
    admin_value_input = ft.TextField(label="수정 금액")

    def admin_update(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        target = safe_key(admin_name_input.value)
        raw = admin_value_input.value.replace(",", "").strip()

        if not target:
            show_msg("수정할 닉네임을 입력하세요.")
            return

        if not raw.isdigit():
            show_msg("수정 금액을 숫자로 입력하세요.")
            return

        if db.reference(f"users/{target}").get() is None:
            show_msg("존재하지 않는 닉네임입니다.")
            return

        value = int(raw)
        month = get_month()

        db.reference(f"rankings/{month}/{target}").set(value)
        db.reference(f"users/{target}/monthly_total/{month}").set(value)

        db.reference("logs").push({
            "type": "admin_score_update",
            "target": target,
            "value": value,
            "admin": get_my_name(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        admin_name_input.value = ""
        admin_value_input.value = ""
        render_ranking()
        page.pubsub.send_all("refresh")
        show_msg("관리자 수정이 완료되었습니다.")

    delete_today_name_input = ft.TextField(label="오늘 기록 삭제할 닉네임")

    def admin_delete_today(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        target = safe_key(delete_today_name_input.value)
        if not target:
            show_msg("닉네임을 입력하세요.")
            return

        month = get_month()
        today = get_today()

        daily_ref = db.reference(f"daily/{month}/{target}/{today}")
        daily_data = daily_ref.get()

        if daily_data is None:
            show_msg("오늘 기록이 없습니다.")
            return

        profit = 0
        if isinstance(daily_data, dict):
            profit = int(daily_data.get("profit", 0) or 0)
        else:
            profit = int(daily_data or 0)

        ranking_ref = db.reference(f"rankings/{month}/{target}")
        current_total = int(ranking_ref.get() or 0)
        new_total = max(0, current_total - profit)

        daily_ref.delete()
        ranking_ref.set(new_total)
        db.reference(f"users/{target}/monthly_total/{month}").set(new_total)

        db.reference("logs").push({
            "type": "admin_delete_today",
            "target": target,
            "deleted_profit": profit,
            "admin": get_my_name(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        delete_today_name_input.value = ""
        render_ranking()
        page.pubsub.send_all("refresh")
        show_msg("오늘 기록 삭제가 완료되었습니다.")

    def show_admin_logs(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        logs = db.reference("logs").get() or {}
        if not logs:
            show_msg("관리자 로그가 없습니다.")
            return

        items = list(logs.values())[-20:]
        lines = []
        for item in items:
            if not isinstance(item, dict):
                continue
            t = item.get("time", "")
            typ = item.get("type", "")
            admin = item.get("admin", "")
            if typ == "admin_score_update":
                lines.append(f"{t} | {admin} | 수정 | {item.get('target')} → {int(item.get('value', 0)):,}원")
            elif typ == "admin_rename":
                lines.append(f"{t} | {admin} | 닉네임변경 | {item.get('old')} → {item.get('new')}")
            elif typ == "admin_password_change":
                lines.append(f"{t} | {admin} | 비밀번호변경 | {item.get('target')}")
            elif typ == "admin_delete_today":
                lines.append(f"{t} | {admin} | 오늘기록삭제 | {item.get('target')} / {int(item.get('deleted_profit', 0)):,}원")
            elif typ == "admin_block_user":
                lines.append(f"{t} | {admin} | 사용자차단(구버전) | {item.get('target')}")
            elif typ == "admin_unblock_user":
                lines.append(f"{t} | {admin} | 차단해제(구버전) | {item.get('target')}")
            elif typ == "admin_block_device":
                lines.append(f"{t} | {admin} | 기기차단 | {item.get('target')} / {item.get('device_count', 0)}개")
            elif typ == "admin_unblock_device":
                lines.append(f"{t} | {admin} | 기기차단해제 | {item.get('target')} / {item.get('device_count', 0)}개")
            elif typ == "admin_reset_device":
                lines.append(f"{t} | {admin} | 기기초기화 | {item.get('target')} / {item.get('reset_count', 0)}개")
            elif typ == "signup_request":
                lines.append(f"{t} | 가입신청 | {item.get('target')} / {item.get('phone', '')}")
            elif typ == "signup_approved":
                lines.append(f"{t} | {admin} | 가입승인 | {item.get('target')} / {item.get('phone', '')}")
            elif typ == "signup_rejected":
                lines.append(f"{t} | {admin} | 가입거절 | {item.get('target')}")
            elif typ == "admin_backup_firebase":
                lines.append(f"{t} | {admin} | 백업저장 | {item.get('file')}")
            else:
                lines.append(str(item))

        show_msg("\n".join(lines[-20:]))

    block_user_input = ft.TextField(label="기기 차단할 닉네임")
    unblock_user_input = ft.TextField(label="기기 차단 해제할 닉네임")
    reset_device_input = ft.TextField(label="기기 초기화할 닉네임")

    def admin_block_user(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        target = safe_key(block_user_input.value)
        if not target:
            show_msg("기기 차단할 닉네임을 입력하세요.")
            return

        user_data = db.reference(f"users/{target}").get()
        devices = db.reference("devices").get() or {}

        target_device_ids = []

        # users에 저장된 device_id 우선 확인
        if isinstance(user_data, dict) and user_data.get("device_id"):
            target_device_ids.append(user_data.get("device_id"))

        # devices 경로에서 해당 닉네임으로 잠긴 기기 추가 확인
        for device_id, device_data in devices.items():
            nickname = device_data.get("nickname") if isinstance(device_data, dict) else device_data
            if nickname == target and device_id not in target_device_ids:
                target_device_ids.append(device_id)

        if not target_device_ids:
            show_msg("해당 닉네임에 연결된 기기를 찾지 못했습니다.")
            return

        for device_id in target_device_ids:
            db.reference(f"blocked_devices/{device_id}").set({
                "nickname": target,
                "blocked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "admin": get_my_name(),
            })
            # 기존 기기 잠금 해제: 이 기기는 blocked_devices 때문에 재가입/로그인 불가
            db.reference(f"devices/{device_id}").delete()

        # 닉네임 자체는 차단하지 않음.
        # 단, 기존 계정은 삭제해서 다른 정상 기기에서 같은 닉네임 재가입이 가능하게 함.
        db.reference(f"users/{target}").delete()

        # 차단한 사람은 현재 월 랭킹/오늘 입력 현황에서도 바로 제거
        current_month = get_month()
        db.reference(f"rankings/{current_month}/{target}").delete()
        db.reference(f"daily/{current_month}/{target}").delete()

        db.reference("logs").push({
            "type": "admin_block_device",
            "target": target,
            "device_count": len(target_device_ids),
            "admin": get_my_name(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        block_user_input.value = ""
        render_ranking()
        show_msg(f"{target}님의 기기 {len(target_device_ids)}개를 가입/로그인 차단했습니다.")

    def admin_unblock_user(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        target = safe_key(unblock_user_input.value)
        if not target:
            show_msg("기기 차단 해제할 닉네임을 입력하세요.")
            return

        blocked_devices = db.reference("blocked_devices").get() or {}
        count = 0

        for device_id, device_data in blocked_devices.items():
            nickname = device_data.get("nickname") if isinstance(device_data, dict) else device_data
            if nickname == target:
                db.reference(f"blocked_devices/{device_id}").delete()
                count += 1

        db.reference("logs").push({
            "type": "admin_unblock_device",
            "target": target,
            "device_count": count,
            "admin": get_my_name(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        unblock_user_input.value = ""
        show_msg(f"{target}님의 기기 차단 해제 완료 ({count}개)")

    def admin_reset_device(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        target = safe_key(reset_device_input.value)
        if not target:
            show_msg("기기 초기화할 닉네임을 입력하세요.")
            return

        devices = db.reference("devices").get() or {}
        count = 0

        for device_id, device_data in devices.items():
            nickname = device_data.get("nickname") if isinstance(device_data, dict) else device_data
            if nickname == target:
                db.reference(f"devices/{device_id}").delete()
                count += 1

        db.reference("logs").push({
            "type": "admin_reset_device",
            "target": target,
            "reset_count": count,
            "admin": get_my_name(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        reset_device_input.value = ""
        show_msg(f"{target} 기기 초기화 완료 ({count}개)")

    def admin_show_users(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        users = db.reference("users").get() or {}
        if not users:
            show_msg("가입된 사용자가 없습니다.")
            return

        lines = [f"- {name}" for name in sorted(users.keys())]
        show_msg("\n".join(lines))

    def admin_show_blocked(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        blocked = db.reference("blocked_devices").get() or {}
        if not blocked:
            show_msg("차단된 기기가 없습니다.")
            return

        lines = []
        for device_id, data in blocked.items():
            if isinstance(data, dict):
                nickname = data.get("nickname", "알 수 없음")
                blocked_at = data.get("blocked_at", "")
            else:
                nickname = str(data)
                blocked_at = ""
            lines.append(f"- {nickname} / {device_id[:8]}... / {blocked_at}")

        show_msg("\n".join(lines))

    def admin_backup_firebase(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        try:
            all_data = db.reference("/").get() or {}

            backup_dir = os.path.join(current_dir, "firebase_backups")
            os.makedirs(backup_dir, exist_ok=True)

            filename = f"firebase_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            backup_path = os.path.join(backup_dir, filename)

            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)

            db.reference("logs").push({
                "type": "admin_backup_firebase",
                "file": filename,
                "admin": get_my_name(),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

            show_msg(f"백업 완료\n파일명: {filename}\n폴더: firebase_backups")
        except Exception as ex:
            show_msg(f"백업 실패: {ex}")

    rename_old_input = ft.TextField(label="기존 닉네임")
    rename_new_input = ft.TextField(label="새 닉네임")

    def admin_rename(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        old = safe_key(rename_old_input.value)
        new = safe_key(rename_new_input.value)

        if not old or not new:
            show_msg("기존 닉네임과 새 닉네임을 모두 입력하세요.")
            return

        if old == new:
            show_msg("기존 닉네임과 새 닉네임이 같습니다.")
            return

        old_user_ref = db.reference(f"users/{old}")
        old_user = old_user_ref.get()

        if old_user is None:
            show_msg("기존 닉네임이 존재하지 않습니다.")
            return

        if db.reference(f"users/{new}").get() is not None:
            show_msg("새 닉네임이 이미 존재합니다.")
            return

        # users 이동
        # 닉네임 필드도 새 닉네임으로 같이 바꿔둬야 접속 중인 사용자가 차단으로 오해되지 않습니다.
        if isinstance(old_user, dict):
            old_user["nickname"] = new
        db.reference(f"users/{new}").set(old_user)
        old_user_ref.delete()

        # devices 닉네임도 함께 변경
        devices = db.reference("devices").get() or {}
        old_user_device_id = old_user.get("device_id") if isinstance(old_user, dict) else None

        # users에 저장된 device_id가 있으면 그 기기는 무조건 새 닉네임으로 연결
        if old_user_device_id:
            db.reference(f"devices/{old_user_device_id}").set({
                "nickname": new,
                "locked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

        # devices 목록에서도 기존 닉네임으로 연결된 기기를 모두 새 닉네임으로 변경
        for device_id, device_data in devices.items():
            nickname = device_data.get("nickname") if isinstance(device_data, dict) else device_data
            if nickname == old:
                db.reference(f"devices/{device_id}").set({
                    "nickname": new,
                    "locked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })

        # rankings 전체 월 이동
        all_rankings = db.reference("rankings").get() or {}
        for month_key, month_data in all_rankings.items():
            if isinstance(month_data, dict) and old in month_data:
                db.reference(f"rankings/{month_key}/{new}").set(month_data[old])
                db.reference(f"rankings/{month_key}/{old}").delete()

        # daily 전체 월 이동
        all_daily = db.reference("daily").get() or {}
        for month_key, month_data in all_daily.items():
            if isinstance(month_data, dict) and old in month_data:
                db.reference(f"daily/{month_key}/{new}").set(month_data[old])
                db.reference(f"daily/{month_key}/{old}").delete()

        db.reference("logs").push({
            "type": "admin_rename",
            "old": old,
            "new": new,
            "admin": get_my_name(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        # 접속 중인 사용자 화면에도 새 닉네임을 즉시 반영
        page.pubsub.send_all(f"nickname_changed::{old}::{new}")

        rename_old_input.value = ""
        rename_new_input.value = ""
        render_ranking()
        show_msg("닉네임 변경이 완료되었습니다.")

    approve_signup_input = ft.TextField(label="승인할 닉네임")
    reject_signup_input = ft.TextField(label="거절할 닉네임")

    def show_pending_signups(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        pending = db.reference("pending_users").get() or {}
        if not pending:
            show_msg("가입 승인 대기자가 없습니다.")
            return

        lines = ["가입 승인 대기 목록", ""]
        for name, data in pending.items():
            if not isinstance(data, dict):
                continue
            phone = data.get("phone", "")
            requested_at = data.get("requested_at", "")
            lines.append(f"- {name} / {phone} / {requested_at}")

        show_msg("\n".join(lines))

    def approve_signup(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        target = safe_key(approve_signup_input.value)
        if not target:
            show_msg("승인할 닉네임을 입력하세요.")
            return

        pending_ref = db.reference(f"pending_users/{target}")
        pending = pending_ref.get()

        if pending is None or not isinstance(pending, dict):
            show_msg("해당 닉네임의 가입 신청이 없습니다.")
            return

        if db.reference(f"users/{target}").get() is not None:
            show_msg("이미 가입된 닉네임입니다.")
            pending_ref.delete()
            return

        device_id = pending.get("device_id")
        phone = pending.get("phone", "")
        pw = pending.get("password", "")

        if device_id and db.reference(f"blocked_devices/{device_id}").get() is not None:
            show_msg("차단된 기기의 가입 신청입니다. 승인할 수 없습니다.")
            return

        db.reference(f"users/{target}").set({
            "password": pw,
            "phone": phone,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "approved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "approved_by": get_my_name(),
            "device_locked": True,
            "device_id": device_id,
            "status": "approved",
        })

        if device_id:
            db.reference(f"devices/{device_id}").set({
                "nickname": target,
                "locked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

        month = get_month()
        db.reference(f"rankings/{month}/{target}").set(0)
        db.reference(f"users/{target}/monthly_total/{month}").set(0)

        pending_ref.delete()

        db.reference("logs").push({
            "type": "signup_approved",
            "target": target,
            "phone": phone,
            "admin": get_my_name(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        approve_signup_input.value = ""
        render_ranking()
        page.pubsub.send_all("refresh")
        show_msg(f"{target} 가입을 승인했습니다. 해당 사용자는 자동으로 입장됩니다.")

    def reject_signup(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        target = safe_key(reject_signup_input.value)
        if not target:
            show_msg("거절할 닉네임을 입력하세요.")
            return

        pending_ref = db.reference(f"pending_users/{target}")
        pending = pending_ref.get()
        if pending is None:
            show_msg("해당 닉네임의 가입 신청이 없습니다.")
            return

        pending_ref.delete()
        db.reference("logs").push({
            "type": "signup_rejected",
            "target": target,
            "admin": get_my_name(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        reject_signup_input.value = ""
        show_msg(f"{target} 가입 신청을 거절했습니다.")

    change_pw_name_input = ft.TextField(label="비밀번호 바꿀 닉네임")
    change_pw_new_input = ft.TextField(
        label="새 비밀번호 숫자 4자리",
        password=True,
        can_reveal_password=True,
        keyboard_type=ft.KeyboardType.NUMBER,
    )

    def admin_change_password(e):
        if not admin_mode["enabled"]:
            show_msg("관리자 모드를 먼저 여세요.")
            return

        target = safe_key(change_pw_name_input.value)
        new_pw = (change_pw_new_input.value or "").strip()

        if not target:
            show_msg("비밀번호를 바꿀 닉네임을 입력하세요.")
            return

        if not new_pw.isdigit() or len(new_pw) != 4:
            show_msg("새 비밀번호는 숫자 4자리로 입력하세요.")
            return

        user_ref = db.reference(f"users/{target}")
        user_data = user_ref.get()

        if user_data is None:
            show_msg("존재하지 않는 닉네임입니다.")
            return

        user_ref.update({
            "password": new_pw,
            "password_changed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "password_changed_by": get_my_name(),
        })

        db.reference("logs").push({
            "type": "admin_password_change",
            "target": target,
            "admin": get_my_name(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        change_pw_name_input.value = ""
        change_pw_new_input.value = ""
        page.update()
        show_msg(f"{target}님의 비밀번호를 변경했습니다.")

    admin_content = ft.Column(scroll=ft.ScrollMode.AUTO)

    def set_admin_menu(menu_name):
        admin_content.controls.clear()

        if menu_name == "금액":
            admin_content.controls.extend([
                ft.Text("수정", weight=ft.FontWeight.BOLD),
                admin_name_input,
                admin_value_input,
                ft.ElevatedButton("수정", on_click=admin_update),
            ])

        elif menu_name == "기록":
            admin_content.controls.extend([
                ft.Text("오늘 기록 삭제", weight=ft.FontWeight.BOLD),
                delete_today_name_input,
                ft.ElevatedButton("오늘 기록 삭제", on_click=admin_delete_today),
            ])

        elif menu_name == "가입승인":
            admin_content.controls.extend([
                ft.Text("가입 승인 대기", weight=ft.FontWeight.BOLD),
                ft.ElevatedButton("가입 신청 목록 보기", on_click=show_pending_signups),
                ft.Divider(),
                approve_signup_input,
                ft.ElevatedButton("가입 승인", on_click=approve_signup),
                ft.Divider(),
                reject_signup_input,
                ft.ElevatedButton("가입 거절", on_click=reject_signup),
            ])

        elif menu_name == "사용자":
            admin_content.controls.extend([
                ft.Text("기기 차단 / 차단 해제", weight=ft.FontWeight.BOLD),
                block_user_input,
                ft.ElevatedButton("해당 기기 가입 차단", on_click=admin_block_user),
                unblock_user_input,
                ft.ElevatedButton("차단 해제", on_click=admin_unblock_user),
                ft.Divider(),
                ft.Text("기기 초기화", weight=ft.FontWeight.BOLD),
                reset_device_input,
                ft.ElevatedButton("기기 초기화", on_click=admin_reset_device),
                ft.Divider(),
                ft.Text("사용자 목록", weight=ft.FontWeight.BOLD),
                ft.ElevatedButton("전체 사용자 보기", on_click=admin_show_users),
                ft.ElevatedButton("차단 기기 목록 보기", on_click=admin_show_blocked),
            ])

        elif menu_name == "비밀번호":
            admin_content.controls.extend([
                ft.Text("비밀번호 변경", weight=ft.FontWeight.BOLD),
                ft.Text("가입된 사용자의 로그인 비밀번호를 숫자 4자리로 변경합니다.", size=12),
                change_pw_name_input,
                change_pw_new_input,
                ft.ElevatedButton("비밀번호 변경", on_click=admin_change_password),
            ])

        elif menu_name == "로그":
            admin_content.controls.extend([
                ft.Text("관리자 로그 / 백업", weight=ft.FontWeight.BOLD),
                ft.ElevatedButton("최근 관리자 로그 보기", on_click=show_admin_logs),
                ft.Divider(),
                ft.Text("Firebase 전체 백업", weight=ft.FontWeight.BOLD),
                ft.ElevatedButton("Firebase 백업 저장", on_click=admin_backup_firebase),
            ])

        elif menu_name == "닉네임":
            admin_content.controls.extend([
                ft.Text("닉네임 변경", weight=ft.FontWeight.BOLD),
                rename_old_input,
                rename_new_input,
                ft.ElevatedButton("닉네임 변경", on_click=admin_rename),
            ])

        page.update()

    admin_menu = ft.Row(
        wrap=True,
        controls=[
            ft.ElevatedButton("금액", on_click=lambda e: set_admin_menu("금액")),
            ft.ElevatedButton("기록", on_click=lambda e: set_admin_menu("기록")),
            ft.ElevatedButton("사용자", on_click=lambda e: set_admin_menu("사용자")),
            ft.ElevatedButton("가입승인", on_click=lambda e: set_admin_menu("가입승인")),
            ft.ElevatedButton("비밀번호", on_click=lambda e: set_admin_menu("비밀번호")),
            ft.ElevatedButton("로그", on_click=lambda e: set_admin_menu("로그")),
            ft.ElevatedButton("닉네임", on_click=lambda e: set_admin_menu("닉네임")),
        ])

    admin_section.controls = [
        ft.Divider(),
        ft.Row([
            ft.Text("🔧 관리자 모드", size=18, weight=ft.FontWeight.BOLD),
            ft.TextButton("닫기", on_click=close_admin_mode),
        ]),
        ft.Text("관리자 메뉴를 선택하세요.", size=12),
        admin_menu,
        ft.Divider(),
        admin_content,
    ]

    set_admin_menu("금액")

    # ---------- 로그인 / 회원가입 팝업 ----------
    nickname_input = ft.TextField(label="닉네임", autofocus=True)
    phone_input = ft.TextField(label="휴대폰번호", keyboard_type=ft.KeyboardType.PHONE)
    password_input = ft.TextField(label="비밀번호 숫자 4자리", password=True, can_reveal_password=True, keyboard_type=ft.KeyboardType.NUMBER)
    login_message = ft.Text("회원가입은 닉네임/휴대폰번호/숫자4자리 비밀번호 입력 후 신청하세요. 관리자가 승인해야 이용 가능합니다.", size=12)

    pending_login = {"name": None, "password": None, "checking": False, "token": 0}
    pending_status_text = ft.Text(
        "⏳ 가입 승인 대기중입니다\n관리자 승인 후 이용 가능합니다.",
        size=16,
        weight=ft.FontWeight.BOLD,
    )
    pending_hint_text = ft.Text("승인되면 자동으로 입장합니다. 잠시만 기다려주세요.", size=12)
    blocked_text = ft.Text("🚫 관리자에 의해 가입 차단되어 이용할 수 없습니다.", size=16, weight=ft.FontWeight.BOLD)

    login_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("로그인 / 회원가입"),
        content=ft.Column(
            controls=[
                nickname_input,
                password_input,
                phone_input,
                login_message,
            ],
            tight=True,
            width=320),
        actions=[],
        actions_alignment=ft.MainAxisAlignment.END)

    def get_saved_nickname():
        try:
            return page.client_storage.get("saved_nickname")
        except Exception:
            return None

    def set_saved_nickname(name):
        try:
            page.client_storage.set("saved_nickname", name)
        except Exception:
            pass

    def close_login_dialog():
        login_dialog.open = False
        page.update()

    def login_success(name, user_ref):
        """승인 완료 후 자동 로그인 처리"""
        pending_login["checking"] = False
        set_device_locked_nickname(name)
        user_info["name"] = name
        user_ref.update({
            "status": "approved",
            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "device_id": get_device_id(),
        })

        login_dialog.open = False
        pending_screen.visible = False
        try:
            blocked_screen.visible = False
        except NameError:
            pass
        app_content.visible = True
        set_logged_in_ui()
        render_ranking()
        page.update()
        show_msg(f"{name}님 로그인 완료")

    def start_auto_approval_checker():
        name = pending_login.get("name")
        pw = pending_login.get("password")
        if not name or not pw:
            return

        pending_login["token"] += 1
        token = pending_login["token"]
        pending_login["checking"] = True

        def approval_worker():
            while pending_login.get("checking") and pending_login.get("token") == token:
                time.sleep(3)
                try:
                    current_name = pending_login.get("name")
                    current_pw = pending_login.get("password")
                    if not current_name or not current_pw:
                        continue

                    user_data = db.reference(f"users/{current_name}").get()
                    if isinstance(user_data, dict) and user_data.get("status") == "approved":
                        if user_data.get("password") == current_pw:
                            pending_login["checking"] = False
                            page.pubsub.send_all(f"approved_login::{current_name}")
                            break
                        pending_login["checking"] = False
                        pending_hint_text.value = "비밀번호 정보가 맞지 않습니다. 로그인 화면에서 다시 로그인해주세요."
                        login_dialog.open = True
                        pending_screen.visible = False
                        page.update()
                        break

                    pending = db.reference(f"pending_users/{current_name}").get()
                    if pending is None:
                        pending_login["checking"] = False
                        page.pubsub.send_all(f"approval_rejected::{current_name}")
                        break
                except Exception:
                    pass

        threading.Thread(target=approval_worker, daemon=True).start()

    def show_pending_wait_screen(name, pw):
        pending_login["name"] = name
        pending_login["password"] = pw
        login_dialog.open = False
        app_content.visible = False
        try:
            blocked_screen.visible = False
        except NameError:
            pass
        pending_screen.visible = True
        pending_status_text.value = f"⏳ {name}님 가입 승인 대기중입니다\n관리자 승인 후 자동으로 입장합니다."
        pending_hint_text.value = "승인되면 자동으로 입장합니다. 잠시만 기다려주세요."
        page.update()
        start_auto_approval_checker()

    def check_approval_status(e=None):
        name = pending_login.get("name")
        pw = pending_login.get("password")

        if not name or not pw:
            pending_hint_text.value = "가입 신청 정보가 없습니다. 다시 회원가입 신청을 해주세요."
            login_dialog.open = True
            pending_screen.visible = False
            page.update()
            return

        user_ref = db.reference(f"users/{name}")
        data = user_ref.get()

        if isinstance(data, dict) and data.get("status") == "approved":
            if data.get("password") != pw:
                pending_hint_text.value = "비밀번호 정보가 맞지 않습니다. 로그인 화면에서 다시 로그인해주세요."
                login_dialog.open = True
                pending_screen.visible = False
                page.update()
                return
            login_success(name, user_ref)
            return

        pending = db.reference(f"pending_users/{name}").get()
        if pending is None:
            pending_hint_text.value = "가입 신청이 거절되었거나 삭제되었습니다. 관리자에게 문의하세요."
            page.update()
            return

        pending_hint_text.value = "아직 승인 대기중입니다. 관리자 승인 후 다시 확인해주세요."
        page.update()

    def back_to_login_from_pending(e=None):
        pending_login["checking"] = False
        pending_screen.visible = False
        login_dialog.open = True
        page.update()

    def normalize_phone(text):
        return "".join(ch for ch in (text or "") if ch.isdigit())

    def is_valid_4digit_password(pw):
        return len(pw) == 4 and pw.isdigit()

    def do_login(e):
        name = safe_key(nickname_input.value)
        pw = password_input.value.strip()

        if not name or not pw:
            login_message.value = "닉네임과 비밀번호를 모두 입력하세요."
            page.update()
            return

        if is_blocked_user(name):
            login_message.value = "차단된 사용자입니다. 관리자에게 문의하세요."
            page.update()
            return

        device_id = get_device_id()

        if db.reference(f"blocked_devices/{device_id}").get() is not None:
            login_message.value = "이 기기는 사용이 제한되어 있습니다. 관리자에게 문의하세요."
            page.update()
            return

        saved_name = get_device_locked_nickname() or get_saved_nickname()
        if saved_name and saved_name != name:
            login_message.value = f"이 핸드폰은 '{saved_name}' 닉네임으로만 이용할 수 있습니다."
            page.update()
            return

        user_ref = db.reference(f"users/{name}")
        data = user_ref.get()

        if data is None:
            pending = db.reference(f"pending_users/{name}").get()
            if isinstance(pending, dict):
                if pending.get("password") == pw:
                    show_pending_wait_screen(name, pw)
                else:
                    login_message.value = "비밀번호가 틀렸습니다."
                    page.update()
            else:
                login_message.value = "가입된 닉네임이 아닙니다. 회원가입 신청을 먼저 해주세요."
                page.update()
            return

        if data.get("status") and data.get("status") != "approved":
            login_message.value = "가입 승인 대기중입니다. 관리자에게 문의하세요."
            page.update()
            return

        if data.get("password") != pw:
            login_message.value = "비밀번호가 틀렸습니다."
            page.update()
            return

        set_device_locked_nickname(name)
        user_info["name"] = name
        user_ref.update({
            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "device_id": get_device_id(),
        })

        close_login_dialog()
        set_logged_in_ui()
        render_ranking()
        show_msg(f"{name}님 로그인 완료")

    def do_register(e):
        name = safe_key(nickname_input.value)
        phone = normalize_phone(phone_input.value)
        pw = password_input.value.strip()

        if not name or not phone or not pw:
            login_message.value = "닉네임, 휴대폰번호, 비밀번호를 모두 입력하세요."
            page.update()
            return

        if len(phone) < 10 or len(phone) > 11:
            login_message.value = "휴대폰번호를 정확히 입력하세요. 예: 01012345678"
            page.update()
            return

        if not is_valid_4digit_password(pw):
            login_message.value = "비밀번호는 숫자 4자리만 가능합니다."
            page.update()
            return

        if is_blocked_user(name):
            login_message.value = "사용할 수 없는 닉네임입니다. 관리자에게 문의하세요."
            page.update()
            return

        device_id = get_device_id()

        if db.reference(f"blocked_devices/{device_id}").get() is not None:
            login_message.value = "이 기기는 사용이 제한되어 있습니다. 관리자에게 문의하세요."
            page.update()
            return

        saved_name = get_device_locked_nickname() or get_saved_nickname()
        if saved_name:
            login_message.value = f"이 핸드폰은 이미 '{saved_name}' 닉네임으로 가입되어 있습니다."
            page.update()
            return

        if db.reference(f"users/{name}").get() is not None:
            login_message.value = "이미 존재하는 닉네임입니다. 다른 닉네임을 사용하세요."
            page.update()
            return

        if db.reference(f"pending_users/{name}").get() is not None:
            login_message.value = "이미 가입 신청이 접수되었습니다. 관리자 승인을 기다려주세요."
            page.update()
            return

        db.reference(f"pending_users/{name}").set({
            "nickname": name,
            "phone": phone,
            "password": pw,
            "device_id": device_id,
            "requested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "pending",
        })

        db.reference("logs").push({
            "type": "signup_request",
            "target": name,
            "phone": phone,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        login_message.value = "가입 신청 완료. 관리자 승인을 기다려주세요."
        show_pending_wait_screen(name, pw)
        show_msg("가입 신청이 접수되었습니다. 관리자 승인 후 이용 가능합니다.")

    login_dialog.actions = [
        ft.TextButton("로그인", on_click=do_login),
        ft.ElevatedButton("회원가입", on_click=do_register),
    ]

    def start_block_monitor():
        """접속 중인 사용자가 차단되면 몇 초 안에 자동으로 화면에서 내보냅니다."""
        def block_worker():
            while True:
                time.sleep(3)
                try:
                    name = get_my_name()
                    if name and is_current_user_blocked():
                        page.pubsub.send_all(f"force_logout::{name}")
                except Exception:
                    pass

        threading.Thread(target=block_worker, daemon=True).start()

    start_block_monitor()

    # ---------- 새로고침 ----------
    def manual_refresh(e=None):
        render_ranking()

    def background_refresh():
        while True:
            time.sleep(60)
            try:
                render_ranking()
            except Exception:
                pass

    threading.Thread(target=background_refresh, daemon=True).start()

    # ---------- 페이지 배치 ----------
    def admin_trophy_press_start(e):
        admin_press["start"] = time.time()

    def admin_trophy_press_end(e):
        start = admin_press.get("start")
        admin_press["start"] = None
        if start and time.time() - start >= 3:
            admin_press["ready"] = True
            show_msg("한번 더 눌러주세요")

    def admin_trophy_click(e):
        if admin_press.get("ready"):
            admin_press["ready"] = False
            show_admin_unlock()

    title = ft.Row(
        spacing=4,
        controls=[
            ft.GestureDetector(
                content=ft.Text("🏆", size=25, weight=ft.FontWeight.BOLD),
                on_long_press_start=admin_trophy_press_start,
                on_long_press_end=admin_trophy_press_end,
                on_tap=admin_trophy_click,
            ),
            ft.Text("일일 순수익 순위", size=25, weight=ft.FontWeight.BOLD),
        ],
    )
    app_content = ft.Column(
        visible=False,
        controls=[
            title,
            date_text,
            info_text,
            ft.ElevatedButton("지난달 기록 보기", on_click=show_previous_month_total),
            ft.ElevatedButton("새로고침", on_click=manual_refresh),
            status_text,
            ft.ElevatedButton("오늘 입력 현황 보기", on_click=show_today_status),
            rank_list,
            profit_input,
            quick_buttons,
            record_btn,
            ft.Divider(),
            admin_unlock_row,
            admin_section,
        ],
    )

    pending_screen = ft.Column(
        visible=False,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Container(height=80),
            pending_status_text,
            pending_hint_text,
            ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.TextButton("로그인 화면", on_click=back_to_login_from_pending),
                ],
            ),
        ],
    )

    blocked_screen = ft.Column(
        visible=False,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Container(height=120),
            blocked_text,
            ft.Text("관리자에게 문의하세요.", size=12),
        ],
    )

    page.add(app_content, pending_screen, blocked_screen)

    # 처음 접속 시 항상 로그인 팝업 표시
    saved_name = get_device_locked_nickname() or get_saved_nickname()
    if saved_name:
        nickname_input.value = saved_name
        login_message.value = f"이 핸드폰은 '{saved_name}' 닉네임으로 등록되어 있습니다. 비밀번호를 입력하고 로그인하세요."

    page.overlay.append(login_dialog)
    login_dialog.open = True

    render_ranking()
    page.update()


ft.app(target=main, port=8550, view=ft.AppView.WEB_BROWSER)
