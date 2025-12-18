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

# ----------------------------------------------------------------------------
# [핵심 수정] 비밀번호 안전하게 가져오기 (어디에 적었든 찾아냄)
# ----------------------------------------------------------------------------
def get_password():
    # 1. secrets.toml 최상단에 있는 경우
    if "admin_password" in st.secrets:
        return st.secrets["admin_password"]
    # 2. [connections.gsheets] 안에 잘못 넣은 경우 (흔한 실수 방지)
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        if "admin_password" in st.secrets["connections"]["gsheets"]:
            return st.secrets["connections"]["gsheets"]["admin_password"]
    # 3. 없으면 기본값
    return "admin1234"

ADMIN_PASSWORD = get_password()

# ============================================================================
# 2. 데이터 처리 함수 (캐싱 & 오류 방지)
# ============================================================================

@st.cache_resource
def get_connection():
    """구글 시트 연결 객체 생성 (리소스 캐싱)"""
    return st.connection("gsheets", type=GSheetsConnection)

def get_empty_structure(sheet_name):
    """시트가 비어있을 때 사용할 기본 구조 정의"""
    structures = {
        'labs': ['name'],
        'equipment': ['name'],
        'bookings': ['id', 'user_name', 'lab', 'equipment', 'date', 'start_time', 'end_time', 'password'],
        'water': ['date', 'user_name', 'lab', 'amount'],
        'logs': ['timestamp', 'action', 'user', 'details']
    }
    return pd.DataFrame(columns=structures.get(sheet_name, []))

@st.cache_data(ttl=60) 
def load_sheet_cached(sheet_name):
    """데이터 로드 및 무결성 검사"""
    conn = get_connection()
    try:
        # ttl=0으로 읽어서 최신 상태 확인 시도, 실패 시 캐시 사용 로직은 st.connection 내부 처리
        df = conn.read(worksheet=sheet_name, ttl=60)
        
        # 데이터가 아예 없거나 컬럼이 깨진 경우 방어
        if df is None or df.empty or len(df.columns) == 0:
            return get_empty_structure(sheet_name)
        
        # 불필요한 'Unnamed' 컬럼이나 빈 컬럼 제거
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
        df = df.fillna('') # NaN을 빈 문자열로 변환 (에러 방지)
        
        # 필수 컬럼이 있는지 확인 (없으면 빈 구조 반환하여 KeyError 방지)
        required_col = get_empty_structure(sheet_name).columns
        if not set(required_col).issubset(df.columns):
            return get_empty_structure(sheet_name)

        return df.astype(str)
        
    except Exception:
        return get_empty_structure(sheet_name)

def save_sheet(sheet_name, df):
    """데이터 저장 및 캐시 초기화"""
    conn = get_connection()
    try:
        # 빈 행 제거 및 문자열 변환
        df = df.dropna(how='all').fillna('').astype(str)
        conn.update(worksheet=sheet_name, data=df)
        st.cache_data.clear() # 저장 후 즉시 반영을 위해 캐시 삭제
        return True
    except Exception as e:
        st.error(f"데이터 저장 실패: {e}")
        return False

def add_log(action, user, details):
    """로그 기록 (오류가 나도 메인 기능은 멈추지 않음)"""
    try:
        df_log = load_sheet_cached('logs')
        new_log = pd.DataFrame([{
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'action': action,
            'user': user,
            'details': details
        }])
        
        if df_log.empty:
            df_log = new_log
        else:
            df_log = pd.concat([df_log, new_log], ignore_index=True)
            
        save_sheet('logs', df_log)
    except:
        pass

# ============================================================================
# 3. 헬퍼 함수
# ============================================================================

def parse_time(time_str):
    if not time_str or len(time_str) != 4 or not time_str.isdigit(): return None
    h, m = int(time_str[:2]), int(time_str[2:])
    if not (0 <= h <= 23 and 0 <= m <= 59): return None
    return f"{h:02d}:{m:02d}"

def check_overlap(df, date_str, eq_name, start_time, end_time):
    if df.empty: return False, ""
    try:
        same = df[(df['date'] == date_str) & (df['equipment'] == eq_name)].copy()
        if same.empty: return False, ""
        
        # 시간 문자열 정리 (HH:MM 형식 보장)
        same['start_time'] = same['start_time'].astype(str).str[:5]
        same['end_time'] = same['end_time'].astype(str).str[:5]
        
        for _, row in same.iterrows():
            if (row['start_time'] < end_time) and (row['end_time'] > start_time):
                return True, str(row['user_name'])
        return False, ""
    except:
        return False, ""

def calculate_hours(start_str, end_str):
    try:
        end_min = 24 * 60 if end_str == "24:00" else int(end_str.split(':')[0])*60 + int(end_str.split(':')[1])
        start_min = int(start_str.split(':')[0])*60 + int(start_str.split(':')[1])
        return (end_min - start_min) / 60.0
    except: return 0.0

# ============================================================================
# 4. 데이터 로드 및 UI 구성
# ============================================================================

# 데이터 로드
df_labs = load_sheet_cached('labs')
df_equipment = load_sheet_cached('equipment')

LABS = df_labs['name'].tolist() if not df_labs.empty else []
EQUIPMENT = df_equipment['name'].tolist() if not df_equipment.empty else []

if LABS: lab_scale = alt.Scale(domain=LABS, scheme='tableau20')
else: lab_scale = alt.Scale(scheme='tableau20')

st.title("🔬 실험실 공동 기기 예약 시스템")

tab1, tab2, tab3, tab4 = st.tabs(["📅 예약하기", "📊 타임라인", "💧 3차수", "👮 관리자"])

# --- TAB 1: 예약하기 ---
with tab1:
    if not LABS or not EQUIPMENT:
        st.warning("⚠️ 초기 설정이 필요합니다. 관리자 모드에서 랩/기기를 등록해주세요.")
    else:
        col1, col2 = st.columns([1, 1.5])
        with col1:
            st.subheader("📝 새 예약")
            user_name = st.text_input("이름", placeholder="홍길동")
            user_lab = st.selectbox("실험실", LABS)
            st.divider()
            date = st.date_input("날짜", datetime.now())
            eq_name = st.selectbox("기기", EQUIPMENT)
            st.info("⏱️ 시간: 4자리 (0900)\n🌙 오버나이트 자동 처리")
            c1, c2 = st.columns(2)
            start_str = c1.text_input("시작", placeholder="0900", max_chars=4)
            end_str = c2.text_input("종료", placeholder="1730", max_chars=4)
            password = st.text_input("비밀번호 (4자리)", type="password", max_chars=4)
            
            if st.button("🎯 예약 등록", type="primary", use_container_width=True):
                fs, fe = parse_time(start_str), parse_time(end_str)
                if not user_name or len(password) != 4: st.error("이름/비번 확인")
                elif not fs or not fe: st.error("시간 형식 오류")
                else:
                    df_bk = load_sheet_cached('bookings')
                    if fe < fs: # Overnight
                        nd = date + timedelta(days=1)
                        ov1, u1 = check_overlap(df_bk, str(date), eq_name, fs, "24:00")
                        ov2, u2 = check_overlap(df_bk, str(nd), eq_name, "00:00", fe)
                        if ov1 or ov2: st.error(f"충돌! ({u1 if ov1 else u2})")
                        else:
                            bid = datetime.now().strftime('%Y%m%d%H%M%S')
                            new_rows = pd.DataFrame([
                                {'id': f"{bid}_1", 'user_name': user_name, 'lab': user_lab, 'equipment': eq_name, 'date': str(date), 'start_time': fs, 'end_time': "24:00", 'password': password},
                                {'id': f"{bid}_2", 'user_name': user_name, 'lab': user_lab, 'equipment': eq_name, 'date': str(nd), 'start_time': "00:00", 'end_time': fe, 'password': password}
                            ])
                            df_bk = pd.concat([df_bk, new_rows], ignore_index=True)
                            if save_sheet('bookings', df_bk):
                                add_log("예약(OV)", user_name, eq_name)
                                st.success("예약 완료!"); st.rerun()
                    else:
                        ov, user = check_overlap(df_bk, str(date), eq_name, fs, fe)
                        if ov: st.error(f"충돌! ({user})")
                        else:
                            new_row = pd.DataFrame([{
                                'id': datetime.now().strftime('%Y%m%d%H%M%S'), 'user_name': user_name, 'lab': user_lab, 
                                'equipment': eq_name, 'date': str(date), 'start_time': fs, 'end_time': fe, 'password': password
                            }])
                            df_bk = pd.concat([df_bk, new_row], ignore_index=True)
                            if save_sheet('bookings', df_bk):
                                add_log("예약", user_name, eq_name)
                                st.success("예약 완료!"); st.rerun()

        with col2:
            st.markdown(f"### 📊 {date} - {eq_name}")
            df_bk = load_sheet_cached('bookings')
            df_filt = df_bk[(df_bk['date'] == str(date)) & (df_bk['equipment'] == eq_name)].copy()
            
            if not df_filt.empty:
                df_filt['start'] = pd.to_datetime(df_filt['date'] + ' ' + df_filt['start_time'].str[:5], format='%Y-%m-%d %H:%M')
                df_filt['end'] = pd.to_datetime(df_filt['date'] + ' ' + df_filt['end_time'].str[:5].replace("24:00","23:59"), format='%Y-%m-%d %H:%M')
                
                chart = alt.Chart(df_filt).mark_bar(cornerRadius=5).encode(
                    x=alt.X('user_name', title='예약자'),
                    y=alt.Y('start:T', scale=alt.Scale(domain=[pd.to_datetime(f"{date} 00:00"), pd.to_datetime(f"{date} 23:59")]), title='시간'),
                    y2='end:T', color=alt.Color('lab', scale=lab_scale), tooltip=['user_name', 'start_time', 'end_time']
                ).properties(height=500)
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("예약 없음")
            
            st.divider()
            st.subheader("🔧 내 예약 관리")
            # 현재 시간 이후 예약만 표시
            now_dt = datetime.now()
            my_bookings = []
            for _, r in df_bk[df_bk['equipment'] == eq_name].iterrows():
                try:
                    r_dt = datetime.strptime(f"{r['date']} {r['end_time'][:5].replace('24:00','23:59')}", "%Y-%m-%d %H:%M")
                    if r_dt >= now_dt: my_bookings.append(r)
                except: continue
            
            if my_bookings:
                for b in my_bookings:
                    with st.expander(f"📅 {b['date']} | {b['user_name']} | {b['start_time']}~{b['end_time']}"):
                        kp = st.text_input("비밀번호", type="password", key=f"p_{b['id']}")
                        if st.button("삭제", key=f"d_{b['id']}"):
                            if kp == b['password']:
                                df_new = df_bk[df_bk['id'] != b['id']]
                                if save_sheet('bookings', df_new):
                                    add_log("삭제", b['user_name'], eq_name)
                                    st.success("삭제됨"); st.rerun()
                            else: st.error("비번 불일치")
            else: st.info("예약 내역 없음")

# --- TAB 2: 타임라인 ---
with tab2:
    st.subheader("🕐 기기별 24시간 현황")
    td = st.date_input("날짜", datetime.now(), key="t2_d")
    df_bk = load_sheet_cached('bookings')
    df_d = df_bk[df_bk['date'] == str(td)].copy()
    
    if not df_d.empty:
        df_d['s_dt'] = pd.to_datetime(df_d['date'] + ' ' + df_d['start_time'].str[:5], format='%Y-%m-%d %H:%M')
        df_d['e_dt'] = pd.to_datetime(df_d['date'] + ' ' + df_d['end_time'].str[:5].replace("24:00","23:59"), format='%Y-%m-%d %H:%M')
        
        ch = alt.Chart(df_d).mark_bar().encode(
            x=alt.X('s_dt:T', scale=alt.Scale(domain=[pd.to_datetime(f"{td} 00:00"), pd.to_datetime(f"{td} 23:59")]), title='시간'),
            x2='e_dt:T', y='equipment', color=alt.Color('lab', scale=lab_scale), tooltip=['user_name', 'lab']
        ).properties(height=400)
        st.altair_chart(ch, use_container_width=True)
    else: st.info("예약 없음")

# --- TAB 3: 3차수 ---
with tab3:
    c1, c2 = st.columns([1, 1.5])
    with c1:
        st.subheader("💧 사용량 기록")
        with st.form("wf"):
            wn = st.text_input("이름")
            wl = st.selectbox("실험실", LABS) if LABS else None
            wa = st.number_input("사용량 (L)", min_value=0.1, step=0.5)
            if st.form_submit_button("저장") and wn:
                df_w = load_sheet_cached('water')
                new_w = pd.DataFrame([{'date': datetime.now().strftime('%Y-%m-%d'), 'user_name': wn, 'lab': wl, 'amount': str(wa)}])
                df_w = pd.concat([df_w, new_w], ignore_index=True)
                if save_sheet('water', df_w):
                    add_log("3차수", wn, f"{wa}L")
                    st.success("저장됨"); st.rerun()
        st.dataframe(load_sheet_cached('water').tail(5), use_container_width=True)
    
    with c2:
        st.subheader("📊 통계")
        df_w = load_sheet_cached('water')
        if not df_w.empty:
            df_w['amount'] = pd.to_numeric(df_w['amount'], errors='coerce')
            df_w['mon'] = pd.to_datetime(df_w['date']).dt.strftime('%Y-%m')
            
            # 이번달 파이차트
            cm = datetime.now().strftime('%Y-%m')
            df_m = df_w[df_w['mon'] == cm]
            if not df_m.empty:
                st.markdown(f"#### 📅 {cm}")
                pie_d = df_m.groupby('lab')['amount'].sum().reset_index()
                base = alt.Chart(pie_d).encode(theta=alt.Theta("amount", stack=True))
                pie = base.mark_arc(innerRadius=60).encode(color=alt.Color("lab", scale=lab_scale), tooltip=['lab', 'amount'])
                st.altair_chart(pie, use_container_width=True)
            
            # 월별 막대
            st.markdown("#### 📈 월별 추이")
            bar_d = df_w.groupby(['mon', 'lab'])['amount'].sum().reset_index()
            bar = alt.Chart(bar_d).mark_bar().encode(x='mon', y='amount', color=alt.Color('lab', scale=lab_scale)).properties(height=300)
            st.altair_chart(bar, use_container_width=True)

# --- TAB 4: 관리자 ---
with tab4:
    st.subheader("👮 관리자")
    apw = st.text_input("비밀번호", type="password", key="adm_pw")
    if apw == ADMIN_PASSWORD:
        st.success("접속 승인")
        at1, at2, at3, at4 = st.tabs(["⚙️ 설정", "📅 예약", "💧 3차수", "📜 로그"])
        
        with at1:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 🧪 실험실")
                # [핵심] hide_index=True로 인덱스 충돌 방지, key 추가로 중복 ID 방지
                d_lab = st.data_editor(load_sheet_cached('labs'), num_rows="dynamic", use_container_width=True, key="ed_lab", hide_index=True)
                if st.button("저장", key="btn_lab"):
                    if save_sheet('labs', d_lab): st.success("완료"); st.rerun()
            with c2:
                st.markdown("#### 🔬 기기")
                d_eq = st.data_editor(load_sheet_cached('equipment'), num_rows="dynamic", use_container_width=True, key="ed_eq", hide_index=True)
                if st.button("저장", key="btn_eq"):
                    if save_sheet('equipment', d_eq): st.success("완료"); st.rerun()
        
        with at2:
            st.warning("데이터 직접 수정")
            d_bk = st.data_editor(load_sheet_cached('bookings'), num_rows="dynamic", use_container_width=True, key="ed_bk", hide_index=True)
            if st.button("예약 저장", key="btn_bk"): save_sheet('bookings', d_bk); st.success("완료")
            
        with at3:
            st.warning("데이터 직접 수정")
            d_wt = st.data_editor(load_sheet_cached('water'), num_rows="dynamic", use_container_width=True, key="ed_wt", hide_index=True)
            if st.button("3차수 저장", key="btn_wt"): save_sheet('water', d_wt); st.success("완료")
            
        with at4:
            try:
                st.dataframe(load_sheet_cached('logs').sort_values(by='timestamp', ascending=False), use_container_width=True, hide_index=True)
            except: st.info("로그 없음")