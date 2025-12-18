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

# [비밀번호]
def get_password():
    if "admin_password" in st.secrets:
        return st.secrets["admin_password"]
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        if "admin_password" in st.secrets["connections"]["gsheets"]:
            return st.secrets["connections"]["gsheets"]["admin_password"]
    return "admin1234"

ADMIN_PASSWORD = get_password()

# 색상 팔레트
def get_lab_scale(labs):
    if not labs: return alt.Scale(scheme='tableau20')
    return alt.Scale(domain=labs, scheme='tableau20')

# ---------------------------------------------------------
# 2. 데이터 처리 엔진
# ---------------------------------------------------------
@st.cache_resource
def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def clean_val(val):
    s = str(val).strip()
    if s.lower() in ['nan', 'none', '', '<na>']: return ""
    if s.endswith('.0'): return s[:-2]
    return s

def get_empty_df(sheet_name):
    cols = {
        'labs': ['name'],
        'equipment': ['name'],
        'bookings': ['id', 'user_name', 'lab', 'equipment', 'date', 'start_time', 'end_time', 'password'],
        'water': ['date', 'user_name', 'lab', 'amount'],
        'logs': ['timestamp', 'action', 'user', 'details']
    }
    return pd.DataFrame(columns=cols.get(sheet_name, []))

@st.cache_data(ttl=5)
def load_data(sheet_name):
    conn = get_connection()
    try:
        df = conn.read(worksheet=sheet_name, ttl=0)
        if df is None or df.empty: return get_empty_df(sheet_name)
        df = df.astype(str).applymap(clean_val)
        
        req = get_empty_df(sheet_name).columns
        if not set(req).issubset(df.columns): return get_empty_df(sheet_name)
        
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.strftime('%Y-%m-%d')
            df = df.dropna(subset=['date'])
            
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

def parse_time(time_str):
    if not time_str or len(time_str) != 4 or not time_str.isdigit(): return None
    h, m = int(time_str[:2]), int(time_str[2:])
    if not (0 <= h <= 23 and 0 <= m <= 59): return None
    return f"{h:02d}:{m:02d}"

def calculate_hours(start_str, end_str):
    try:
        em = 24*60 if end_str == "24:00" else int(end_str.split(':')[0])*60 + int(end_str.split(':')[1])
        sm = int(start_str.split(':')[0])*60 + int(start_str.split(':')[1])
        return (em - sm) / 60.0
    except: return 0.0

def check_overlap(df, date_str, eq_name, start_time, end_time, exclude_id=None):
    if df.empty: return False, ""
    try:
        if exclude_id: df = df[df['id'] != exclude_id]
        same = df[(df['date'] == date_str) & (df['equipment'] == eq_name)]
        if same.empty: return False, ""
        
        for _, r in same.iterrows():
            if (row['start_time'] < end_time) and (row['end_time'] > start_time):
                return True, row['user_name']
        return False, ""
    except: return False, ""

def batch_rename(target_type, old_name, new_name):
    st.cache_data.clear()
    sheet = 'labs' if target_type == 'lab' else 'equipment'
    df_master = load_data(sheet)
    
    if new_name in df_master['name'].values: return False, "중복 이름"
    
    if old_name in df_master['name'].values:
        df_master.loc[df_master['name'] == old_name, 'name'] = new_name
        save_data(sheet, df_master)
    
    df_bk = load_data('bookings')
    col = 'lab' if target_type == 'lab' else 'equipment'
    if not df_bk.empty and col in df_bk.columns:
        if old_name in df_bk[col].values:
            df_bk.loc[df_bk[col] == old_name, col] = new_name
            save_data('bookings', df_bk)
            
    if target_type == 'lab':
        df_wt = load_data('water')
        if not df_wt.empty and 'lab' in df_wt.columns:
            if old_name in df_wt['lab'].values:
                df_wt.loc[df_wt['lab'] == old_name, 'lab'] = new_name
                save_data('water', df_wt)
    return True, "변경 완료"

# --- [동적 데이터 로드] ---
df_labs_list = load_data('labs')
LABS = df_labs_list['name'].tolist() if not df_labs_list.empty else []

df_eq_list = load_data('equipment')
EQUIPMENT = df_eq_list['name'].tolist() if not df_eq_list.empty else []
lab_scale = get_lab_scale(LABS)

# ---------------------------------------------------------
# 3. UI 및 기능 구현
# ---------------------------------------------------------

st.title("🔬 5개 실험실 공동 기기 예약 시스템")

tab1, tab2, tab3, tab4 = st.tabs(["📅 예약 하기", "📊 전체 타임라인", "💧 3차수 사용량", "👮 관리자 모드"])

# --- [TAB 1] 기기 예약 ---
with tab1:
    if not LABS or not EQUIPMENT:
        st.warning("⚠️ 데이터 로딩 중이거나 초기 설정이 필요합니다.")
        if st.button("🔄 새로고침"):
            st.cache_data.clear()
            st.rerun()
    else:
        col1, col2 = st.columns([1, 1.2])
        with col1:
            st.subheader("📝 새 예약 작성")
            
            # [핵심 변경] st.form 사용 -> 입력 중 화면 리로드(깜빡임) 방지
            with st.form("booking_form"):
                user_name = st.text_input("사용자 이름", placeholder="예: 홍길동")
                user_lab = st.selectbox("소속 실험실", LABS)
                st.divider()
                date = st.date_input("날짜 선택", datetime.now())
                eq_name = st.selectbox("사용 기기", EQUIPMENT)
                
                st.write("---")
                st.write("⏱️ **시간 입력** (예: 1330)")
                st.info("🌙 **오버나이트 예약:** 2300 ~ 0300 입력 시 자동 처리됩니다.")
                
                c1, c2 = st.columns(2)
                s_str = c1.text_input("시작 시간", placeholder="0900", max_chars=4)
                e_str = c2.text_input("종료 시간", placeholder="1000", max_chars=4)
                pw = st.text_input("비밀번호 (4자리)", type="password", max_chars=4)
                
                # 버튼을 form_submit_button으로 변경
                submit = st.form_submit_button("예약 등록하기", type="primary", use_container_width=True)

            if submit:
                fs, fe = parse_time(s_str), parse_time(e_str)
                if not user_name or len(pw) != 4: st.error("이름과 비밀번호를 입력하세요.")
                elif not fs or not fe: st.error("시간 형식이 잘못되었습니다.")
                else:
                    df = load_data('bookings')
                    if fe < fs: # Overnight
                        nd = date + timedelta(days=1)
                        ov1, u1 = check_overlap(df, str(date), eq_name, fs, "24:00")
                        ov2, u2 = check_overlap(df, str(nd), eq_name, "00:00", fe)
                        if ov1 or ov2: st.error(f"❌ 예약 충돌 발생! ({u1 if ov1 else u2}님)")
                        else:
                            bid = datetime.now().strftime('%Y%m%d%H%M%S')
                            new_rows = [
                                {'id': bid+"_1", 'user_name': user_name, 'lab': user_lab, 'equipment': eq_name, 'date': str(date), 'start_time': fs, 'end_time': "24:00", 'password': pw},
                                {'id': bid+"_2", 'user_name': user_name, 'lab': user_lab, 'equipment': eq_name, 'date': str(nd), 'start_time': "00:00", 'end_time': fe, 'password': pw}
                            ]
                            df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
                            save_data('bookings', df)
                            add_log("예약(Overnight)", user_name, f"{eq_name} / {fs}~{fe}")
                            st.success("🌙 오버나이트 예약 완료!"); st.rerun()
                    else:
                        if fs == fe: st.error("시간을 확인하세요.")
                        else:
                            ov, ou = check_overlap(df, str(date), eq_name, fs, fe)
                            if ov: st.error(f"❌ 예약 충돌! ({ou}님)")
                            else:
                                new_row = {'id': datetime.now().strftime('%Y%m%d%H%M%S'), 'user_name': user_name, 'lab': user_lab, 'equipment': eq_name, 'date': str(date), 'start_time': fs, 'end_time': fe, 'password': pw}
                                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                                save_data('bookings', df)
                                add_log("예약 생성", user_name, f"{eq_name} / {str(date)} {fs}~{fe}")
                                st.success("예약 완료!"); st.rerun()

        with col2:
            # 여기서는 form 내부의 date/eq_name을 바로 쓸 수 없으므로,
            # 사용자가 입력 중인 값 대신 기본값이나 가장 최근 선택값을 보여주려면
            # 세션 스테이트나 별도 입력이 필요하지만, 
            # Streamlit 특성상 Form 내부 변수는 Submit 전엔 알 수 없음.
            # -> 해결책: 조회용 날짜/기기 선택기를 Form 밖(위)으로 빼거나,
            #    단순히 현재 상태에서는 예약 현황을 보여주기 위해 별도 selectbox를 둡니다.
            #    하지만 "입력할 때마다 바뀐다"는 불편함을 해소하기 위해
            #    예약 입력 폼과 별개로 '조회용' UI를 살려두는 것이 좋습니다.
            #    여기서는 기존 UI 유지를 위해 '가장 최근에 선택된 값'이 아닌
            #    독립적인 조회 컨트롤을 추가하는 것이 UX상 더 낫지만, 
            #    일단 사용자 요청대로 "화면이 바뀌는 것"만 막기 위해 Form을 적용했습니다.
            #    (주의: Form 안의 date, eq_name은 Submit 전까지 col2에 반영 안 됨)
            
            # [수정] 오른쪽 화면 업데이트를 위해, 예약 입력과는 별개로 '조회' 기능을 살짝 분리하거나
            # 그냥 두면, 왼쪽 폼에서 선택해도 오른쪽이 안 바뀌는 문제가 생김.
            # 따라서, "조회용 컨트롤"을 폼 위로 빼거나 복제해야 함.
            # 사용성을 위해 날짜/기기 선택만 Form 밖으로 뺍니다.
            
            # (수정된 로직 적용을 위해 위의 col1 코드 일부 수정 필요)
            pass 

# --- [UI 구조 재조정: 입력 중 리로드 방지 + 실시간 조회 유지] ---
# 위 코드를 그대로 쓰면 왼쪽에서 날짜를 바꿔도 오른쪽 차트가 안 바뀝니다 (Form 때문).
# 그래서 날짜와 기기 선택은 Form 밖으로 빼고, 이름/시간/비번만 Form 안에 넣겠습니다.

with tab1:
    if not LABS or not EQUIPMENT:
        st.warning("⚠️ 로딩 중...")
    else:
        col1, col2 = st.columns([1, 1.2])
        
        # [공통 컨트롤] 날짜와 기기는 밖으로 뺌 (실시간 조회용)
        with col1:
            st.subheader("📝 새 예약 작성")
            date = st.date_input("날짜 선택", datetime.now())
            eq_name = st.selectbox("사용 기기", EQUIPMENT)
            st.divider()
            
            # [입력 폼] 이름, 실험실, 시간, 비번은 Form으로 감싸서 리로드 방지
            with st.form("booking_inputs"):
                user_name = st.text_input("사용자 이름", placeholder="예: 홍길동")
                user_lab = st.selectbox("소속 실험실", LABS)
                st.write("⏱️ **시간 입력** (예: 1330)")
                c1, c2 = st.columns(2)
                s_str = c1.text_input("시작 시간", placeholder="0900", max_chars=4)
                e_str = c2.text_input("종료 시간", placeholder="1000", max_chars=4)
                pw = st.text_input("비밀번호 (4자리)", type="password", max_chars=4)
                
                submit = st.form_submit_button("예약 등록하기", type="primary", use_container_width=True)

            if submit:
                # (저장 로직은 동일)
                fs, fe = parse_time(s_str), parse_time(e_str)
                if not user_name or len(pw) != 4: st.error("이름과 비밀번호를 입력하세요.")
                elif not fs or not fe: st.error("시간 형식이 잘못되었습니다.")
                else:
                    df = load_data('bookings')
                    if fe < fs: # Overnight
                        nd = date + timedelta(days=1)
                        ov1, u1 = check_overlap(df, str(date), eq_name, fs, "24:00")
                        ov2, u2 = check_overlap(df, str(nd), eq_name, "00:00", fe)
                        if ov1 or ov2: st.error(f"❌ 충돌! ({u1 if ov1 else u2})")
                        else:
                            bid = datetime.now().strftime('%Y%m%d%H%M%S')
                            new_rows = [
                                {'id': bid+"_1", 'user_name': user_name, 'lab': user_lab, 'equipment': eq_name, 'date': str(date), 'start_time': fs, 'end_time': "24:00", 'password': pw},
                                {'id': bid+"_2", 'user_name': user_name, 'lab': user_lab, 'equipment': eq_name, 'date': str(nd), 'start_time': "00:00", 'end_time': fe, 'password': pw}
                            ]
                            df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
                            save_data('bookings', df)
                            add_log("예약(OV)", user_name, f"{eq_name}")
                            st.success("예약 완료!"); st.rerun()
                    else:
                        if fs == fe: st.error("시간 확인")
                        else:
                            ov, ou = check_overlap(df, str(date), eq_name, fs, fe)
                            if ov: st.error(f"❌ 충돌! ({ou})")
                            else:
                                new_row = {'id': datetime.now().strftime('%Y%m%d%H%M%S'), 'user_name': user_name, 'lab': user_lab, 'equipment': eq_name, 'date': str(date), 'start_time': fs, 'end_time': fe, 'password': pw}
                                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                                save_data('bookings', df)
                                add_log("예약", user_name, f"{eq_name}")
                                st.success("예약 완료!"); st.rerun()

        # [오른쪽 화면] 실시간 반응 (날짜/기기 변경 시 바로 바뀜)
        with col2:
            df_cur = load_data('bookings')
            chart_df = pd.DataFrame(columns=['Start', 'End', 'user_name', 'lab', 'start_time', 'end_time'])
            
            if not df_cur.empty: 
                df_cur = df_cur[(df_cur['date'] == str(date)) & (df_cur['equipment'] == eq_name)]
                if not df_cur.empty:
                    chart_df = df_cur.copy()
                    chart_df['start_time'] = chart_df['start_time'].astype(str).str.slice(0, 5)
                    chart_df['end_time'] = chart_df['end_time'].astype(str).str.slice(0, 5)
                    chart_df['viz_end'] = chart_df['end_time'].replace("24:00", "23:59")
                    chart_df['Start'] = pd.to_datetime(chart_df['date'].astype(str) + ' ' + chart_df['start_time'], format='%Y-%m-%d %H:%M')
                    chart_df['End'] = pd.to_datetime(chart_df['date'].astype(str) + ' ' + chart_df['viz_end'], format='%Y-%m-%d %H:%M')

            st.markdown(f"### 📊 {date} <br> {eq_name} 점유 현황", unsafe_allow_html=True)
            
            dom_s = pd.to_datetime(f"{date} 00:00:00")
            dom_e = pd.to_datetime(f"{date} 23:59:59")
            
            timeline = alt.Chart(chart_df).mark_bar(cornerRadius=5).encode(
                x=alt.X('user_name', title='예약자'),
                y=alt.Y('Start', scale=alt.Scale(domain=[dom_s, dom_e]), axis=alt.Axis(format='%H:%M', tickCount=24), title='시간'),
                y2='End', color=alt.Color('lab', scale=lab_scale),
                tooltip=['user_name', 'lab', 'start_time', 'end_time']
            ).properties(height=600, width='container')
            st.altair_chart(timeline, use_container_width=True)

            st.divider()
            st.subheader(f"🔧 예약 관리 ({eq_name})")
            
            df_bk = load_data('bookings')
            if not df_bk.empty:
                df_bk = df_bk[df_bk['equipment'] == eq_name]
                now = datetime.now()
                fut_bk = []
                for _, r in df_bk.iterrows():
                    try:
                        et = "23:59" if r['end_time'] == "24:00" else r['end_time'][:5]
                        if datetime.strptime(f"{r['date']} {et}", "%Y-%m-%d %H:%M") >= now: fut_bk.append(r)
                    except: continue
                
                if fut_bk:
                    df_fut = pd.DataFrame(fut_bk).sort_values(by=['date', 'start_time'])
                    for _, r in df_fut.iterrows():
                        with st.expander(f"📅 {r['date']} | {r['user_name']} | {r['start_time']}~{r['end_time']}"):
                            c1, c2 = st.columns(2)
                            ns = c1.text_input("새 시작", value=r['start_time'].replace(":",""), key=f"ns_{r['id']}")
                            ne = c2.text_input("새 종료", value=r['end_time'].replace(":",""), key=f"ne_{r['id']}")
                            ipw = st.text_input("비밀번호", type="password", key=f"p_{r['id']}")
                            
                            b1, b2 = st.columns(2)
                            if b1.button("수정", key=f"m_{r['id']}"):
                                nfs, nfe = parse_time(ns), parse_time(ne)
                                if nfs and nfe and str(ipw) == str(r['password']):
                                    df_all = load_data('bookings')
                                    # 중복체크 (본인 제외)
                                    ov, u = check_overlap(df_all, r['date'], eq_name, nfs, nfe, exclude_id=r['id'])
                                    if ov: st.error(f"충돌! ({u})")
                                    else:
                                        df_all.loc[df_all['id'] == r['id'], ['start_time', 'end_time']] = [nfs, nfe]
                                        save_data('bookings', df_all)
                                        st.success("수정됨"); st.rerun()
                                else: st.error("오류 (비번/시간)")
                                
                            if b2.button("삭제", key=f"d_{r['id']}"):
                                if str(ipw) == str(r['password']):
                                    df_all = load_data('bookings')
                                    df_all = df_all[df_all['id'] != r['id']]
                                    save_data('bookings', df_all)
                                    st.success("삭제됨"); st.rerun()
                                else: st.error("비번 오류")
                else: st.info("예약 없음")
            else: st.info("예약 없음")

# --- [TAB 2] 전체 타임라인 ---
with tab2:
    st.subheader("🕑 기기별 24시간 전체 현황")
    td = st.date_input("날짜 선택", datetime.now(), key="tl_date")
    df_v = load_data('bookings')
    
    if not df_v.empty:
        df_v = df_v[df_v['date'] == str(td)]
        if not df_v.empty:
            df_v['start_dt'] = pd.to_datetime(df_v['date'].astype(str) + ' ' + df_v['start_time'].astype(str).str.slice(0, 5), format='%Y-%m-%d %H:%M')
            df_v['end_dt'] = pd.to_datetime(df_v['date'].astype(str) + ' ' + df_v['end_time'].astype(str).str.slice(0, 5).replace("24:00", "23:59"), format='%Y-%m-%d %H:%M')
            
            ch = alt.Chart(df_v).mark_bar().encode(
                x=alt.X('start_dt', scale=alt.Scale(domain=[pd.to_datetime(f"{td} 00:00"), pd.to_datetime(f"{td} 23:59")]), title='시간'),
                x2='end_dt', y='equipment', color=alt.Color('lab', scale=lab_scale),
                tooltip=['user_name', 'lab', 'start_time', 'end_time']
            ).properties(height=400)
            st.altair_chart(ch, use_container_width=True)
        else: st.info("예약 없음")
    else: st.info("데이터 없음")

    st.divider()
    st.subheader("📈 기기별 사용 통계")
    if EQUIPMENT:
        seq = st.selectbox("기기 선택", EQUIPMENT)
        dfs = load_data('bookings')
        if not dfs.empty:
            dfs = dfs[dfs['equipment'] == seq]
            if not dfs.empty:
                dfs['dur'] = dfs.apply(lambda x: calculate_hours(x['start_time'], x['end_time']), axis=1)
                dfs['mon'] = pd.to_datetime(dfs['date']).dt.strftime('%Y-%m')
                
                sc1, sc2 = st.columns(2)
                with sc1:
                    cm = datetime.now().strftime('%Y-%m')
                    st.markdown(f"#### 📅 {cm} 점유율")
                    dft = dfs[dfs['mon'] == cm]
                    if not dft.empty:
                        pd_pie = dft.groupby('lab')['dur'].sum().reset_index()
                        pd_pie['pct'] = pd_pie['dur'] / pd_pie['dur'].sum()
                        base = alt.Chart(pd_pie).encode(theta=alt.Theta("dur", stack=True))
                        pie = base.mark_arc(innerRadius=60).encode(color=alt.Color("lab", scale=lab_scale), tooltip=["lab", "dur"])
                        st.altair_chart(pie, use_container_width=True)
                    else: st.info("데이터 없음")
                with sc2:
                    st.markdown("#### 📊 월별 추이")
                    bd = dfs.groupby(['mon', 'lab'])['dur'].sum().reset_index()
                    bar = alt.Chart(bd).mark_bar().encode(x='mon', y='dur', color=alt.Color('lab', scale=lab_scale)).properties(height=300)
                    st.altair_chart(bar, use_container_width=True)
            else: st.info("데이터 없음")
        else: st.info("데이터 없음")

# --- [TAB 3] 3차수 ---
with tab3:
    col1, col2 = st.columns([1, 1.5])
    df_w = load_data('water')
    
    with col1:
        st.subheader("💧 사용량 기록")
        with st.form("wf"):
            wn = st.text_input("이름")
            wl = st.selectbox("실험실", LABS) if LABS else None
            wa = st.number_input("사용량 (L)", min_value=0.1, step=0.5)
            if st.form_submit_button("저장"):
                new_w = pd.DataFrame([{'date': datetime.now().strftime('%Y-%m-%d'), 'user_name': wn, 'lab': wl, 'amount': str(wa)}])
                df_w = pd.concat([df_w, new_w], ignore_index=True)
                save_data('water', df_w)
                add_log("3차수", wn, f"{wa}L")
                st.success("저장됨"); st.rerun()
        if not df_w.empty: st.dataframe(df_w.tail(5), use_container_width=True, hide_index=True)

    with col2:
        st.subheader("📊 통계 대시보드")
        if not df_w.empty:
            df_w['amount'] = pd.to_numeric(df_w['amount'], errors='coerce')
            df_w['mon'] = pd.to_datetime(df_w['date']).dt.strftime('%Y-%m')
            cm = datetime.now().strftime('%Y-%m')
            
            st.markdown(f"#### 📅 {cm} 점유율")
            dftm = df_w[df_w['mon'] == cm] if not df_w.empty else pd.DataFrame()
            if not dftm.empty:
                ms = dftm.groupby('lab')['amount'].sum().reset_index()
                base = alt.Chart(ms).encode(theta=alt.Theta("amount", stack=True))
                pie = base.mark_arc(innerRadius=60).encode(color=alt.Color("lab", scale=lab_scale), tooltip=["lab", "amount"])
                st.altair_chart(pie, use_container_width=True)
            else: st.info("데이터 없음")
            
            st.divider()
            st.markdown("#### 📈 월별 추이")
            mst = df_w.groupby(['mon', 'lab'])['amount'].sum().reset_index()
            bar = alt.Chart(mst).mark_bar().encode(x='mon', y='amount', color=alt.Color('lab', scale=lab_scale)).properties(height=350)
            st.altair_chart(bar, use_container_width=True)
        else: st.info("데이터 없음")

# --- [TAB 4] 관리자 ---
with tab4:
    st.subheader("👮 관리자 페이지")
    if st.text_input("관리자 비밀번호", type="password") == ADMIN_PASSWORD:
        st.success("접속 승인")
        at1, at2, at3, at4 = st.tabs(["⚙️설정", "📅예약", "💧3차수", "📜로그"])
        
        with at1:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 🧪 실험실 관리")
                dle = st.data_editor(load_data('labs'), num_rows="dynamic", key="ed_lab", hide_index=True)
                if st.button("실험실 저장", key="sv_lab"): save_data('labs', dle); st.success("저장됨"); st.rerun()
                with st.expander("이름 일괄 변경"):
                    ol, nl = st.selectbox("변경 전", LABS, key='ol'), st.text_input("변경 후", key='nl')
                    if st.button("적용", key='bl'):
                        suc, msg = batch_rename('lab', ol, nl)
                        if suc: st.success("완료"); st.rerun()
                        else: st.error(msg)
            with c2:
                st.markdown("#### 🔬 기기 관리")
                dee = st.data_editor(load_data('equipment'), num_rows="dynamic", key="ed_eq", hide_index=True)
                if st.button("기기 저장", key="sv_eq"): save_data('equipment', dee); st.success("저장됨"); st.rerun()
                with st.expander("이름 일괄 변경"):
                    oe, ne = st.selectbox("변경 전", EQUIPMENT, key='oe'), st.text_input("변경 후", key='ne')
                    if st.button("적용", key='be'):
                        suc, msg = batch_rename('equipment', oe, ne)
                        if suc: st.success("완료"); st.rerun()
                        else: st.error(msg)

        with at2:
            st.warning("예약 데이터 강제 수정")
            dbk = st.data_editor(load_data('bookings'), num_rows="dynamic", key="ed_bk", hide_index=True)
            if st.button("예약 저장", key="sv_bk"): save_data('bookings', dbk); st.success("저장됨")

        with at3:
            st.warning("3차수 데이터 강제 수정")
            dwt = st.data_editor(load_data('water'), num_rows="dynamic", key="ed_wt", hide_index=True)
            if st.button("물 데이터 저장", key="sv_wt"): save_data('water', dwt); st.success("저장됨")

        with at4:
            try: st.dataframe(load_data('logs').sort_values(by='timestamp', ascending=False), use_container_width=True, hide_index=True)
            except: st.info("로그 없음")