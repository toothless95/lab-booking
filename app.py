import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import altair as alt
from streamlit_gsheets import GSheetsConnection

# ============================================================================
# 1. 설정 및 초기화
# ============================================================================
st.set_page_config(
    page_title="실험실 통합 예약 시스템", 
    layout="wide", 
    page_icon="🔬"
)

# [비밀번호] secrets 또는 기본값 (로컬 테스트용)
def get_password():
    if "admin_password" in st.secrets:
        return st.secrets["admin_password"]
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        if "admin_password" in st.secrets["connections"]["gsheets"]:
            return st.secrets["connections"]["gsheets"]["admin_password"]
    return "admin1234"

ADMIN_PASSWORD = get_password()

# 색상 팔레트 (레거시 코드 유지)
LAB_COLORS = {
    'Lab1': '#1f77b4', 'Lab2': '#ff7f0e', 'Lab3': '#2ca02c', 
    'Lab4': '#d62728', 'Lab5': '#9467bd'
}
# 색상이 없으면 기본 색상 사용
def get_lab_scale(labs):
    if not labs: return alt.Scale(scheme='tableau20')
    return alt.Scale(domain=labs, scheme='tableau20')

# ============================================================================
# 2. 구글 시트 데이터 핸들링 (핵심 엔진)
# ============================================================================

@st.cache_resource
def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def clean_val(val):
    """숫자 뒤 .0 제거 및 NaN 처리 (비밀번호/ID 오류 방지)"""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', '']: return ""
    if s.endswith('.0'): return s[:-2]
    return s

def get_empty_df(sheet_name):
    """빈 시트 구조 정의"""
    cols = {
        'labs': ['name'],
        'equipment': ['name'],
        'bookings': ['id', 'user_name', 'lab', 'equipment', 'date', 'start_time', 'end_time', 'password'],
        'water': ['date', 'user_name', 'lab', 'amount'],
        'logs': ['timestamp', 'action', 'user', 'details']
    }
    return pd.DataFrame(columns=cols.get(sheet_name, []))

@st.cache_data(ttl=10) # 빠른 반영을 위해 캐시 시간 단축
def load_data(sheet_name):
    conn = get_connection()
    try:
        df = conn.read(worksheet=sheet_name, ttl=0)
        if df is None or df.empty or len(df.columns) == 0:
            return get_empty_df(sheet_name)
        
        # 전체 데이터 클리닝 (소수점 제거 등)
        df = df.astype(str).applymap(clean_val)
        
        # 필수 컬럼 체크
        req = get_empty_df(sheet_name).columns
        if not set(req).issubset(df.columns):
            return get_empty_df(sheet_name)
            
        return df
    except:
        return get_empty_df(sheet_name)

def save_data(sheet_name, df):
    conn = get_connection()
    try:
        df = df.fillna('').astype(str).applymap(clean_val)
        conn.update(worksheet=sheet_name, data=df)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

def add_log(action, user, details):
    try:
        df_log = load_data('logs')
        new_row = pd.DataFrame([{
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'action': action, 'user': user, 'details': details
        }])
        df_log = pd.concat([df_log, new_row], ignore_index=True)
        save_data('logs', df_log)
    except: pass

# ============================================================================
# 3. 로직 함수 (시간 계산, 중복 체크, 일괄 변경)
# ============================================================================

def parse_time(t):
    if not t or len(t) != 4 or not t.isdigit(): return None
    h, m = int(t[:2]), int(t[2:])
    if not (0 <= h <= 23 and 0 <= m <= 59): return None
    return f"{h:02d}:{m:02d}"

def calculate_hours(s, e):
    try:
        end_m = 24*60 if e == "24:00" else int(e[:2])*60 + int(e[3:])
        start_m = int(s[:2])*60 + int(s[3:])
        return (end_m - start_m) / 60.0
    except: return 0.0

def check_overlap(df, date_str, eq, start, end, exclude_id=None):
    if df.empty: return False, ""
    try:
        if exclude_id: df = df[df['id'] != exclude_id]
        # 해당 날짜, 해당 기기 필터링
        target = df[(df['date'] == date_str) & (df['equipment'] == eq)]
        if target.empty: return False, ""
        
        for _, r in target.iterrows():
            # 기존 예약 시간
            rs, re = r['start_time'][:5], r['end_time'][:5]
            # 겹침 조건: (기존시작 < 종료) AND (기존종료 > 시작)
            if rs < end and re > start:
                return True, r['user_name']
        return False, ""
    except: return False, ""

def batch_rename(target_type, old_name, new_name):
    """
    [기능 복구] 이름 변경 시 모든 연관 데이터 자동 업데이트
    """
    # 1. 마스터 데이터 수정
    master_sheet = 'labs' if target_type == 'lab' else 'equipment'
    df_master = load_data(master_sheet)
    
    if new_name in df_master['name'].values:
        return False, "이미 존재하는 이름입니다."
    
    if old_name in df_master['name'].values:
        df_master.loc[df_master['name'] == old_name, 'name'] = new_name
        save_data(master_sheet, df_master)
    
    # 2. 예약 내역(bookings) 수정
    df_bk = load_data('bookings')
    col = 'lab' if target_type == 'lab' else 'equipment'
    if not df_bk.empty and col in df_bk.columns:
        if old_name in df_bk[col].values:
            df_bk.loc[df_bk[col] == old_name, col] = new_name
            save_data('bookings', df_bk)
            
    # 3. 물 사용량(water) 수정 (실험실인 경우만)
    if target_type == 'lab':
        df_wt = load_data('water')
        if not df_wt.empty and 'lab' in df_wt.columns:
            if old_name in df_wt['lab'].values:
                df_wt.loc[df_wt['lab'] == old_name, 'lab'] = new_name
                save_data('water', df_wt)
                
    return True, "변경 완료"

# ============================================================================
# 4. 데이터 로드 및 UI 시작
# ============================================================================

df_labs = load_data('labs')
df_eq = load_data('equipment')

LABS = df_labs['name'].tolist() if not df_labs.empty else []
EQUIPMENT = df_eq['name'].tolist() if not df_eq.empty else []
lab_scale = get_lab_scale(LABS)

st.title("🔬 5개 실험실 공동 기기 예약 시스템")

tab1, tab2, tab3, tab4 = st.tabs(["📅 예약 하기", "📊 전체 타임라인", "💧 3차수 사용량", "👮 관리자 모드"])

# ----------------------------------------------------------------------------
# TAB 1: 예약 하기 (좌측: 입력 / 우측: 현황 차트)
# ----------------------------------------------------------------------------
with tab1:
    if not LABS or not EQUIPMENT:
        st.error("⚠️ 관리자 모드에서 랩/기기를 먼저 등록해주세요.")
    else:
        col1, col2 = st.columns([1, 1.3])
        
        # [왼쪽] 예약 입력 폼
        with col1:
            st.subheader("📝 예약 작성")
            with st.form("booking_form"):
                u_name = st.text_input("이름")
                u_lab = st.selectbox("실험실", LABS)
                u_date = st.date_input("날짜", datetime.now())
                u_eq = st.selectbox("기기", EQUIPMENT)
                st.write("---")
                c1, c2 = st.columns(2)
                u_start = c1.text_input("시작 (0900)", max_chars=4)
                u_end = c2.text_input("종료 (1800)", max_chars=4)
                u_pw = st.text_input("비밀번호 (4자리 숫자)", type="password", max_chars=4)
                
                if st.form_submit_button("예약 등록", use_container_width=True):
                    fs, fe = parse_time(u_start), parse_time(u_end)
                    
                    if not u_name or len(u_pw) != 4: 
                        st.error("이름과 비밀번호(4자리)를 입력하세요.")
                    elif not fs or not fe: 
                        st.error("시간 형식 오류 (예: 0900)")
                    elif fs == fe:
                        st.error("시작과 종료 시간이 같습니다.")
                    else:
                        df_bk = load_data('bookings')
                        is_overnight = fe < fs
                        
                        if is_overnight: # 오버나이트
                            nd = u_date + timedelta(days=1)
                            ov1, u1 = check_overlap(df_bk, str(u_date), u_eq, fs, "24:00")
                            ov2, u2 = check_overlap(df_bk, str(nd), u_eq, "00:00", fe)
                            
                            if ov1 or ov2: st.error(f"충돌 발생! ({u1 if ov1 else u2})")
                            else:
                                bid = datetime.now().strftime('%Y%m%d%H%M%S')
                                rows = [
                                    {'id': f"{bid}_1", 'user_name': u_name, 'lab': u_lab, 'equipment': u_eq, 'date': str(u_date), 'start_time': fs, 'end_time': "24:00", 'password': u_pw},
                                    {'id': f"{bid}_2", 'user_name': u_name, 'lab': u_lab, 'equipment': u_eq, 'date': str(nd), 'start_time': "00:00", 'end_time': fe, 'password': u_pw}
                                ]
                                df_bk = pd.concat([df_bk, pd.DataFrame(rows)], ignore_index=True)
                                save_data('bookings', df_bk)
                                add_log("예약(OV)", u_name, u_eq)
                                st.success("🌙 오버나이트 예약 완료!"); st.rerun()
                        else: # 일반 예약
                            ov, usr = check_overlap(df_bk, str(u_date), u_eq, fs, fe)
                            if ov: st.error(f"충돌 발생! ({usr}님이 사용중)")
                            else:
                                row = pd.DataFrame([{
                                    'id': datetime.now().strftime('%Y%m%d%H%M%S'), 'user_name': u_name, 'lab': u_lab, 
                                    'equipment': u_eq, 'date': str(u_date), 'start_time': fs, 'end_time': fe, 'password': u_pw
                                }])
                                df_bk = pd.concat([df_bk, row], ignore_index=True)
                                save_data('bookings', df_bk)
                                add_log("예약", u_name, u_eq)
                                st.success("✅ 예약 완료!"); st.rerun()

        # [오른쪽] 현황 차트 & 내 예약 관리
        with col2:
            st.markdown(f"### 📊 {u_date} : {u_eq} 현황")
            st.caption("다른 사용자의 예약도 모두 표시됩니다.")
            
            df_all = load_data('bookings')
            # 해당 날짜, 해당 기기의 '모든' 예약 필터링
            df_viz = df_all[(df_all['date'] == str(u_date)) & (df_all['equipment'] == u_eq)].copy()
            
            if not df_viz.empty:
                df_viz['s_dt'] = pd.to_datetime(df_viz['date'] + ' ' + df_viz['start_time'].str[:5], format='%Y-%m-%d %H:%M')
                df_viz['e_dt'] = pd.to_datetime(df_viz['date'] + ' ' + df_viz['end_time'].str[:5].replace("24:00","23:59"), format='%Y-%m-%d %H:%M')
                
                chart = alt.Chart(df_viz).mark_bar(cornerRadius=5).encode(
                    x=alt.X('user_name', title='예약자'),
                    y=alt.Y('s_dt:T', title='시간', scale=alt.Scale(domain=[pd.to_datetime(f"{u_date} 00:00"), pd.to_datetime(f"{u_date} 23:59")])),
                    y2='e_dt:T',
                    color=alt.Color('lab', scale=lab_scale),
                    tooltip=['user_name', 'start_time', 'end_time', 'lab']
                ).properties(height=500)
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("예약이 없습니다. 자유롭게 사용하세요!")
            
            st.divider()
            st.subheader("🔧 내 예약 수정/삭제")
            my_pw = st.text_input("내 비밀번호 확인", type="password", key="chk_pw")
            
            if my_pw:
                my_bk = df_all[df_all['password'] == my_pw]
                valid_bk = []
                now_dt = datetime.now()
                
                # 지난 예약 제외
                for _, r in my_bk.iterrows():
                    try:
                        et = "23:59" if r['end_time'] == "24:00" else r['end_time'][:5]
                        if datetime.strptime(f"{r['date']} {et}", "%Y-%m-%d %H:%M") >= now_dt:
                            valid_bk.append(r)
                    except: continue
                
                if valid_bk:
                    for b in sorted(valid_bk, key=lambda x: (x['date'], x['start_time'])):
                        with st.expander(f"{b['date']} | {b['equipment']} | {b['start_time']}~{b['end_time']}"):
                            c1, c2 = st.columns(2)
                            new_s = c1.text_input("변경 시작", value=b['start_time'].replace(":",""), key=f"s_{b['id']}")
                            new_e = c2.text_input("변경 종료", value=b['end_time'].replace(":",""), key=f"e_{b['id']}")
                            
                            b1, b2 = st.columns(2)
                            if b1.button("수정", key=f"mod_{b['id']}"):
                                nfs, nfe = parse_time(new_s), parse_time(new_e)
                                if nfs and nfe:
                                    # 중복 체크 (내꺼 제외)
                                    ov, _ = check_overlap(df_all, b['date'], b['equipment'], nfs, nfe, exclude_id=b['id'])
                                    if ov: st.error("시간 충돌!")
                                    else:
                                        df_all.loc[df_all['id']==b['id'], ['start_time','end_time']] = [nfs, nfe]
                                        save_data('bookings', df_all)
                                        st.success("수정됨"); st.rerun()
                                else: st.error("시간 오류")
                                
                            if b2.button("삭제", key=f"del_{b['id']}"):
                                save_data('bookings', df_all[df_all['id'] != b['id']])
                                st.success("삭제됨"); st.rerun()
                else:
                    st.info("수정 가능한 예약이 없습니다.")

# ----------------------------------------------------------------------------
# TAB 2: 전체 타임라인 (복구된 기능)
# ----------------------------------------------------------------------------
with tab2:
    st.subheader("🕑 기기별 24시간 전체 현황")
    t_date = st.date_input("조회 날짜", datetime.now(), key="tl_date")
    
    df_all = load_data('bookings')
    if not df_all.empty:
        df_day = df_all[df_all['date'] == str(t_date)].copy()
        
        if not df_day.empty:
            df_day['s_dt'] = pd.to_datetime(df_day['date'] + ' ' + df_day['start_time'].str[:5], format='%Y-%m-%d %H:%M')
            df_day['e_dt'] = pd.to_datetime(df_day['date'] + ' ' + df_day['end_time'].str[:5].replace("24:00","23:59"), format='%Y-%m-%d %H:%M')
            
            chart = alt.Chart(df_day).mark_bar().encode(
                x=alt.X('s_dt:T', title='시간', scale=alt.Scale(domain=[pd.to_datetime(f"{t_date} 00:00"), pd.to_datetime(f"{t_date} 23:59")])),
                x2='e_dt:T',
                y=alt.Y('equipment:N', title='기기명'),
                color=alt.Color('lab:N', scale=lab_scale, title='실험실'),
                tooltip=['user_name', 'lab', 'start_time', 'end_time']
            ).properties(height=400)
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("예약 내역이 없습니다.")
    else:
        st.info("데이터가 없습니다.")

    # 통계 섹션
    st.divider()
    st.subheader("📈 통계")
    if EQUIPMENT:
        s_eq = st.selectbox("기기 선택", EQUIPMENT, key="stat_eq")
        df_stats = df_all[df_all['equipment'] == s_eq].copy()
        if not df_stats.empty:
            df_stats['hours'] = df_stats.apply(lambda x: calculate_hours(x['start_time'], x['end_time']), axis=1)
            df_stats['mon'] = pd.to_datetime(df_stats['date']).dt.strftime('%Y-%m')
            
            c1, c2 = st.columns(2)
            with c1:
                cur_m = datetime.now().strftime('%Y-%m')
                st.write(f"**이번 달 ({cur_m}) 점유율**")
                df_cur = df_stats[df_stats['mon'] == cur_m]
                if not df_cur.empty:
                    base = alt.Chart(df_cur).encode(theta=alt.Theta("hours", stack=True))
                    pie = base.mark_arc(innerRadius=60).encode(color=alt.Color("lab", scale=lab_scale), tooltip=['lab', 'hours'])
                    st.altair_chart(pie, use_container_width=True)
                else: st.caption("데이터 없음")
            with c2:
                st.write("**월별 추이**")
                bar_d = df_stats.groupby(['mon', 'lab'])['hours'].sum().reset_index()
                bar = alt.Chart(bar_d).mark_bar().encode(x='mon', y='hours', color=alt.Color('lab', scale=lab_scale)).properties(height=300)
                st.altair_chart(bar, use_container_width=True)

# ----------------------------------------------------------------------------
# TAB 3: 3차수 (레거시 유지)
# ----------------------------------------------------------------------------
with tab3:
    c1, c2 = st.columns([1, 1.5])
    with c1:
        st.subheader("💧 사용량 입력")
        with st.form("wt_form"):
            wn = st.text_input("이름")
            wl = st.selectbox("실험실", LABS) if LABS else None
            wa = st.number_input("사용량(L)", 0.1, step=0.5)
            if st.form_submit_button("저장"):
                df_w = load_data('water')
                new_w = pd.DataFrame([{'date': datetime.now().strftime('%Y-%m-%d'), 'user_name': wn, 'lab': wl, 'amount': str(wa)}])
                df_w = pd.concat([df_w, new_w], ignore_index=True)
                save_data('water', df_w)
                add_log("3차수", wn, f"{wa}L")
                st.success("저장됨"); st.rerun()
        st.dataframe(load_data('water').tail(5), use_container_width=True, hide_index=True)
    
    with c2:
        st.subheader("📊 통계")
        df_w = load_data('water')
        if not df_w.empty:
            df_w['amount'] = pd.to_numeric(df_w['amount'], errors='coerce')
            df_w['mon'] = pd.to_datetime(df_w['date']).dt.strftime('%Y-%m')
            
            bar = alt.Chart(df_w).mark_bar().encode(x='mon', y='amount', color=alt.Color('lab', scale=lab_scale)).properties(height=300)
            st.altair_chart(bar, use_container_width=True)

# ----------------------------------------------------------------------------
# TAB 4: 관리자 (일괄 변경 기능 포함)
# ----------------------------------------------------------------------------
with tab4:
    st.subheader("👮 관리자")
    apw = st.text_input("관리자 비밀번호", type="password")
    
    if apw == ADMIN_PASSWORD:
        st.success("접속 승인")
        at1, at2, at3, at4 = st.tabs(["⚙️ 설정", "📅 데이터", "💧 3차수", "📜 로그"])
        
        with at1:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 🧪 실험실")
                d_lab = st.data_editor(load_data('labs'), num_rows="dynamic", key="ed_l", hide_index=True)
                if st.button("저장", key="sv_l"): save_data('labs', d_lab); st.rerun()
                
                with st.expander("🔄 이름 일괄 변경"):
                    if LABS:
                        ol = st.selectbox("변경 전", LABS, key="ol")
                        nl = st.text_input("변경 후", key="nl")
                        if st.button("변경 적용", key="bl"):
                            suc, msg = batch_rename('lab', ol, nl)
                            if suc: st.success(msg); st.rerun()
                            else: st.error(msg)
            
            with c2:
                st.markdown("#### 🔬 기기")
                d_eq = st.data_editor(load_data('equipment'), num_rows="dynamic", key="ed_e", hide_index=True)
                if st.button("저장", key="sv_e"): save_data('equipment', d_eq); st.rerun()
                
                with st.expander("🔄 이름 일괄 변경"):
                    if EQUIPMENT:
                        oe = st.selectbox("변경 전", EQUIPMENT, key="oe")
                        ne = st.text_input("변경 후", key="ne")
                        if st.button("변경 적용", key="be"):
                            suc, msg = batch_rename('equipment', oe, ne)
                            if suc: st.success(msg); st.rerun()
                            else: st.error(msg)
                            
        with at2:
            st.warning("데이터 직접 수정")
            d_bk = st.data_editor(load_data('bookings'), num_rows="dynamic", key="ed_b", hide_index=True)
            if st.button("예약 저장"): save_data('bookings', d_bk); st.success("완료")
            
        with at3:
            st.warning("데이터 직접 수정")
            d_wt = st.data_editor(load_data('water'), num_rows="dynamic", key="ed_w", hide_index=True)
            if st.button("3차수 저장"): save_data('water', d_wt); st.success("완료")
            
        with at4:
            try: st.dataframe(load_data('logs').sort_values(by='timestamp', ascending=False), use_container_width=True, hide_index=True)
            except: st.info("로그 없음")