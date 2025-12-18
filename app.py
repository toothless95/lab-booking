import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import altair as alt
from streamlit_gsheets import GSheetsConnection

# ============================================================================
# 설정 및 초기화
# ============================================================================
st.set_page_config(
    page_title="실험실 통합 예약 시스템", 
    layout="wide", 
    page_icon="🔬"
)

# 관리자 비밀번호
try:
    ADMIN_PASSWORD = st.secrets["admin_password"]
except:
    ADMIN_PASSWORD = "admin1234"

# ============================================================================
# 데이터 캐싱 및 처리 함수 (Rate Limit 방지)
# ============================================================================

@st.cache_resource
def get_connection():
    """구글 시트 연결 (단 1회만 생성)"""
    return st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=60)  # 60초 동안 캐싱
def load_sheet_cached(sheet_name):
    """시트 데이터 로드 (캐싱으로 API 호출 최소화)"""
    conn = get_connection()
    try:
        df = conn.read(worksheet=sheet_name, ttl=60)
        
        if df is None or df.empty or len(df.columns) == 0:
            return get_empty_structure(sheet_name)
        
        # Unnamed 컬럼 제거
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
        df = df.fillna('')
        
        return df.astype(str)
        
    except Exception as e:
        st.warning(f"⚠️ '{sheet_name}' 시트 로드 실패 (캐시된 데이터 사용)")
        return get_empty_structure(sheet_name)

def get_empty_structure(sheet_name):
    """빈 구조 반환"""
    structures = {
        'labs': ['name'],
        'equipment': ['name'],
        'bookings': ['id', 'user_name', 'lab', 'equipment', 'date', 'start_time', 'end_time', 'password'],
        'water': ['date', 'user_name', 'lab', 'amount'],
        'logs': ['timestamp', 'action', 'user', 'details']
    }
    return pd.DataFrame(columns=structures.get(sheet_name, []))

def save_sheet(sheet_name, df):
    """시트 저장 및 캐시 무효화"""
    conn = get_connection()
    try:
        df = df.fillna('').astype(str)
        conn.update(worksheet=sheet_name, data=df)
        
        # 저장 후 해당 시트 캐시만 클리어
        st.cache_data.clear()
        
        return True
    except Exception as e:
        st.error(f"💾 저장 실패: {e}")
        return False

def add_log(action, user, details):
    """로그 추가 (실패해도 메인 기능은 유지)"""
    try:
        df_log = load_sheet_cached('logs')
        new_log = pd.DataFrame([{
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'action': action,
            'user': user,
            'details': details
        }])
        df_log = pd.concat([df_log, new_log], ignore_index=True)
        
        conn = get_connection()
        conn.update(worksheet='logs', data=df_log)
    except:
        pass

# ============================================================================
# 헬퍼 함수
# ============================================================================

def parse_time(time_str):
    """시간 파싱 (0900 -> 09:00)"""
    if not time_str or len(time_str) != 4 or not time_str.isdigit():
        return None
    h, m = int(time_str[:2]), int(time_str[2:])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return f"{h:02d}:{m:02d}"

def check_overlap(df, date_str, eq_name, start_time, end_time):
    """예약 중복 체크"""
    if df.empty:
        return False, ""
    
    try:
        same = df[(df['date'] == date_str) & (df['equipment'] == eq_name)].copy()
        if same.empty:
            return False, ""
        
        same['start_time'] = same['start_time'].astype(str).str[:5]
        same['end_time'] = same['end_time'].astype(str).str[:5]
        
        for _, row in same.iterrows():
            if (row['start_time'] < end_time) and (row['end_time'] > start_time):
                return True, str(row['user_name'])
        
        return False, ""
    except:
        return False, ""

def calculate_hours(start_str, end_str):
    """사용 시간 계산"""
    try:
        if end_str == "24:00":
            end_min = 24 * 60
        else:
            h, m = map(int, end_str.split(':'))
            end_min = h * 60 + m
        
        h, m = map(int, start_str.split(':'))
        start_min = h * 60 + m
        
        return (end_min - start_min) / 60.0
    except:
        return 0.0

# ============================================================================
# 초기 데이터 로드 (캐싱 적용)
# ============================================================================

# 데이터 로드 (Rate Limit 방지를 위해 캐싱)
df_labs = load_sheet_cached('labs')
df_equipment = load_sheet_cached('equipment')

LABS = df_labs['name'].tolist() if not df_labs.empty else []
EQUIPMENT = df_equipment['name'].tolist() if not df_equipment.empty else []

# Altair 색상 스케일
if LABS:
    lab_scale = alt.Scale(domain=LABS, scheme='tableau20')
else:
    lab_scale = alt.Scale(scheme='tableau20')

# ============================================================================
# UI 시작
# ============================================================================

st.title("🔬 실험실 공동 기기 예약 시스템")

# 초기 설정 체크
if not LABS or not EQUIPMENT:
    st.warning("⚠️ 초기 설정이 필요합니다")
    st.info("👉 **관리자 모드** 탭에서 실험실과 기기를 먼저 추가해주세요")

# 탭 구성
tab1, tab2, tab3, tab4 = st.tabs([
    "📅 예약하기", 
    "📊 타임라인", 
    "💧 3차수", 
    "👮 관리자"
])

# ============================================================================
# TAB 1: 예약하기
# ============================================================================
with tab1:
    if not LABS or not EQUIPMENT:
        st.error("❌ 관리자 모드에서 실험실과 기기를 먼저 등록하세요")
    else:
        col1, col2 = st.columns([1, 1.5])
        
        with col1:
            st.subheader("📝 새 예약")
            
            user_name = st.text_input("이름", placeholder="홍길동")
            user_lab = st.selectbox("실험실", LABS)
            st.divider()
            date = st.date_input("날짜", datetime.now())
            eq_name = st.selectbox("기기", EQUIPMENT)
            
            st.write("---")
            st.info("⏱️ 시간은 4자리로 입력 (예: 0900, 1730)\n\n🌙 오버나이트: 2300~0300 입력 시 자동처리")
            
            c1, c2 = st.columns(2)
            start_str = c1.text_input("시작", placeholder="0900", max_chars=4)
            end_str = c2.text_input("종료", placeholder="1730", max_chars=4)
            
            password = st.text_input("비밀번호 (4자리)", type="password", max_chars=4)
            
            if st.button("🎯 예약 등록", type="primary", use_container_width=True):
                if not user_name:
                    st.error("❌ 이름 입력")
                elif len(password) != 4 or not password.isdigit():
                    st.error("❌ 비밀번호는 4자리 숫자")
                else:
                    fs = parse_time(start_str)
                    fe = parse_time(end_str)
                    
                    if not fs or not fe:
                        st.error("❌ 시간 형식 오류 (예: 0900)")
                    elif fs == fe:
                        st.error("❌ 시작/종료 시간이 같음")
                    else:
                        df_bookings = load_sheet_cached('bookings')
                        
                        # 오버나이트 체크
                        if fe < fs:
                            next_day = date + timedelta(days=1)
                            ov1, u1 = check_overlap(df_bookings, str(date), eq_name, fs, "24:00")
                            ov2, u2 = check_overlap(df_bookings, str(next_day), eq_name, "00:00", fe)
                            
                            if ov1 or ov2:
                                st.error(f"❌ 예약 충돌! ({u1 if ov1 else u2}님)")
                            else:
                                base_id = datetime.now().strftime('%Y%m%d%H%M%S')
                                new_bookings = pd.DataFrame([
                                    {'id': f"{base_id}_1", 'user_name': user_name, 'lab': user_lab, 
                                     'equipment': eq_name, 'date': str(date), 'start_time': fs, 
                                     'end_time': "24:00", 'password': password},
                                    {'id': f"{base_id}_2", 'user_name': user_name, 'lab': user_lab, 
                                     'equipment': eq_name, 'date': str(next_day), 'start_time': "00:00", 
                                     'end_time': fe, 'password': password}
                                ])
                                
                                df_bookings = pd.concat([df_bookings, new_bookings], ignore_index=True)
                                
                                if save_sheet('bookings', df_bookings):
                                    add_log("예약(overnight)", user_name, f"{eq_name}")
                                    st.success("🌙 오버나이트 예약 완료!")
                                    st.rerun()
                        else:
                            overlap, ou = check_overlap(df_bookings, str(date), eq_name, fs, fe)
                            
                            if overlap:
                                st.error(f"❌ 예약 충돌! ({ou}님)")
                            else:
                                new_booking = pd.DataFrame([{
                                    'id': datetime.now().strftime('%Y%m%d%H%M%S'),
                                    'user_name': user_name, 'lab': user_lab, 'equipment': eq_name,
                                    'date': str(date), 'start_time': fs, 'end_time': fe, 
                                    'password': password
                                }])
                                
                                df_bookings = pd.concat([df_bookings, new_booking], ignore_index=True)
                                
                                if save_sheet('bookings', df_bookings):
                                    add_log("예약", user_name, f"{eq_name}")
                                    st.success("✅ 예약 완료!")
                                    st.rerun()
        
        with col2:
            st.markdown(f"### 📊 {date} - {eq_name}")
            
            df_bookings = load_sheet_cached('bookings')
            df_filtered = df_bookings[
                (df_bookings['date'] == str(date)) & 
                (df_bookings['equipment'] == eq_name)
            ].copy()
            
            if not df_filtered.empty:
                df_filtered['start_time'] = df_filtered['start_time'].str[:5]
                df_filtered['end_time'] = df_filtered['end_time'].str[:5]
                df_filtered['end_viz'] = df_filtered['end_time'].replace("24:00", "23:59")
                
                df_filtered['Start'] = pd.to_datetime(
                    df_filtered['date'] + ' ' + df_filtered['start_time'],
                    format='%Y-%m-%d %H:%M'
                )
                df_filtered['End'] = pd.to_datetime(
                    df_filtered['date'] + ' ' + df_filtered['end_viz'],
                    format='%Y-%m-%d %H:%M'
                )
                
                domain_start = pd.to_datetime(f"{date} 00:00:00")
                domain_end = pd.to_datetime(f"{date} 23:59:59")
                
                chart = alt.Chart(df_filtered).mark_bar(cornerRadius=5).encode(
                    x=alt.X('user_name:N', title='예약자'),
                    y=alt.Y('Start:T', 
                           scale=alt.Scale(domain=[domain_start, domain_end]),
                           axis=alt.Axis(format='%H:%M', tickCount=24),
                           title='시간'),
                    y2='End:T',
                    color=alt.Color('lab:N', scale=lab_scale, title='실험실'),
                    tooltip=['user_name', 'lab', 'start_time', 'end_time']
                ).properties(height=500)
                
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("📭 예약 없음")
            
            st.divider()
            st.subheader("🔧 내 예약 관리")
            
            now = datetime.now()
            future = []
            
            for _, row in df_bookings[df_bookings['equipment'] == eq_name].iterrows():
                try:
                    et = "23:59" if row['end_time'] == "24:00" else row['end_time'][:5]
                    dt = datetime.strptime(f"{row['date']} {et}", "%Y-%m-%d %H:%M")
                    if dt >= now:
                        future.append(row)
                except:
                    continue
            
            if future:
                for b in sorted(future, key=lambda x: (x['date'], x['start_time'])):
                    with st.expander(f"📅 {b['date']} | 👤 {b['user_name']} | ⏰ {b['start_time']}~{b['end_time']}"):
                        st.write(f"**실험실:** {b['lab']}")
                        pw_input = st.text_input("비밀번호", type="password", key=f"pw_{b['id']}")
                        
                        if st.button("🗑️ 삭제", key=f"del_{b['id']}"):
                            if pw_input == b['password']:
                                df_all = load_sheet_cached('bookings')
                                df_all = df_all[df_all['id'] != b['id']]
                                if save_sheet('bookings', df_all):
                                    add_log("삭제", b['user_name'], f"{b['equipment']}")
                                    st.success("삭제 완료!")
                                    st.rerun()
                            else:
                                st.error("❌ 비밀번호 틀림")
            else:
                st.info("향후 예약 없음")

# ============================================================================
# TAB 2: 타임라인
# ============================================================================
with tab2:
    st.subheader("🕐 기기별 24시간 타임라인")
    
    target_date = st.date_input("날짜", datetime.now(), key="tl_date")
    
    df_bookings = load_sheet_cached('bookings')
    df_day = df_bookings[df_bookings['date'] == str(target_date)].copy()
    
    if not df_day.empty:
        df_day['start_time'] = df_day['start_time'].str[:5]
        df_day['end_time'] = df_day['end_time'].str[:5]
        df_day['end_viz'] = df_day['end_time'].replace("24:00", "23:59")
        
        df_day['start_dt'] = pd.to_datetime(
            df_day['date'] + ' ' + df_day['start_time'],
            format='%Y-%m-%d %H:%M'
        )
        df_day['end_dt'] = pd.to_datetime(
            df_day['date'] + ' ' + df_day['end_viz'],
            format='%Y-%m-%d %H:%M'
        )
        
        domain_start = pd.to_datetime(f"{target_date} 00:00:00")
        domain_end = pd.to_datetime(f"{target_date} 23:59:59")
        
        chart = alt.Chart(df_day).mark_bar().encode(
            x=alt.X('start_dt:T', 
                   scale=alt.Scale(domain=[domain_start, domain_end]),
                   axis=alt.Axis(format='%H:%M', tickCount=24),
                   title='시간'),
            x2='end_dt:T',
            y=alt.Y('equipment:N', title='기기'),
            color=alt.Color('lab:N', scale=lab_scale, title='실험실'),
            tooltip=['user_name', 'lab', 'equipment', 'start_time', 'end_time']
        ).properties(height=400)
        
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("예약 없음")
    
    st.divider()
    st.subheader("📈 기기 통계")
    
    if EQUIPMENT:
        sel_eq = st.selectbox("기기", EQUIPMENT, key="stats_eq")
        df_stats = df_bookings[df_bookings['equipment'] == sel_eq].copy()
        
        if not df_stats.empty:
            df_stats['duration'] = df_stats.apply(
                lambda x: calculate_hours(x['start_time'], x['end_time']),
                axis=1
            )
            df_stats['month'] = pd.to_datetime(df_stats['date']).dt.strftime('%Y-%m')
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 📅 이번 달")
                cm = datetime.now().strftime('%Y-%m')
                df_m = df_stats[df_stats['month'] == cm]
                
                if not df_m.empty:
                    pie_data = df_m.groupby('lab')['duration'].sum().reset_index()
                    pie_data['pct'] = pie_data['duration'] / pie_data['duration'].sum()
                    
                    base = alt.Chart(pie_data).encode(theta=alt.Theta("duration:Q", stack=True))
                    pie = base.mark_arc(innerRadius=60).encode(
                        color=alt.Color("lab:N", scale=lab_scale),
                        tooltip=['lab', alt.Tooltip('duration', format='.1f'), 
                                alt.Tooltip('pct', format='.1%')]
                    )
                    text = base.mark_text(radius=100).encode(
                        text=alt.Text("pct:Q", format=".1%")
                    )
                    
                    st.altair_chart(pie + text, use_container_width=True)
                else:
                    st.info("데이터 없음")
            
            with col2:
                st.markdown("#### 📊 월별")
                ms = df_stats.groupby(['month', 'lab'])['duration'].sum().reset_index()
                
                if not ms.empty:
                    bar = alt.Chart(ms).mark_bar().encode(
                        x='month:N', y='duration:Q',
                        color=alt.Color('lab:N', scale=lab_scale),
                        tooltip=['month', 'lab', alt.Tooltip('duration', format='.1f')]
                    ).properties(height=300)
                    
                    st.altair_chart(bar, use_container_width=True)

# ============================================================================
# TAB 3: 3차수
# ============================================================================
with tab3:
    col1, col2 = st.columns([1, 1.5])
    
    with col1:
        st.subheader("💧 사용량 기록")
        
        with st.form("wf"):
            wn = st.text_input("이름")
            wl = st.selectbox("실험실", LABS) if LABS else None
            wa = st.number_input("사용량 (L)", min_value=0.1, step=0.5)
            
            if st.form_submit_button("💾 저장", use_container_width=True) and LABS:
                if not wn:
                    st.error("이름 입력")
                else:
                    df_water = load_sheet_cached('water')
                    new_water = pd.DataFrame([{
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'user_name': wn, 'lab': wl, 'amount': str(wa)
                    }])
                    
                    df_water = pd.concat([df_water, new_water], ignore_index=True)
                    
                    if save_sheet('water', df_water):
                        add_log("3차수", wn, f"{wa}L")
                        st.success("✅ 완료!")
                        st.rerun()
        
        st.divider()
        st.write("📋 **최근 기록**")
        df_water = load_sheet_cached('water')
        if not df_water.empty:
            st.dataframe(df_water.tail(10), use_container_width=True)
    
    with col2:
        st.subheader("📊 통계")
        
        if not df_water.empty:
            df_water['amount'] = pd.to_numeric(df_water['amount'], errors='coerce')
            df_water['month'] = pd.to_datetime(df_water['date']).dt.strftime('%Y-%m')
            
            cm = datetime.now().strftime('%Y-%m')
            
            st.markdown("#### 📅 이번 달")
            df_m = df_water[df_water['month'] == cm]
            
            if not df_m.empty:
                pie_data = df_m.groupby('lab')['amount'].sum().reset_index()
                pie_data['pct'] = pie_data['amount'] / pie_data['amount'].sum()
                
                base = alt.Chart(pie_data).encode(theta=alt.Theta("amount:Q", stack=True))
                pie = base.mark_arc(innerRadius=60).encode(
                    color=alt.Color("lab:N", scale=lab_scale),
                    tooltip=['lab', 'amount', alt.Tooltip('pct', format='.1%')]
                )
                text = base.mark_text(radius=100).encode(
                    text=alt.Text("pct:Q", format=".1%")
                )
                
                st.altair_chart(pie + text, use_container_width=True)
            
            st.divider()
            st.markdown("#### 📈 월별")
            ms = df_water.groupby(['month', 'lab'])['amount'].sum().reset_index()
            
            if not ms.empty:
                bar = alt.Chart(ms).mark_bar().encode(
                    x='month:N', y='amount:Q',
                    color=alt.Color('lab:N', scale=lab_scale),
                    tooltip=['month', 'lab', 'amount']
                ).properties(height=300)
                
                st.altair_chart(bar, use_container_width=True)

# ============================================================================
# TAB 4: 관리자
# ============================================================================
with tab4:
    st.subheader("👮 관리자")
    
    admin_pw = st.text_input("비밀번호", type="password", key="apw")
    
    if admin_pw == ADMIN_PASSWORD:
        st.success("✅ 접속 승인")
        
        at1, at2, at3, at4 = st.tabs(["⚙️ 설정", "📅 예약", "💧 3차수", "📜 로그"])
        
        with at1:
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 🧪 실험실")
                df_labs_edit = st.data_editor(
                    load_sheet_cached('labs'),
                    num_rows="dynamic",
                    use_container_width=True,
                    key="labs_ed"
                )
                if st.button("💾 저장", key="save_labs"):
                    if save_sheet('labs', df_labs_edit):
                        st.success("완료!")
                        st.rerun()
            
            with col2:
                st.markdown("#### 🔬 기기")
                df_eq_edit = st.data_editor(
                    load_sheet_cached('equipment'),
                    num_rows="dynamic",
                    use_container_width=True,
                    key="eq_ed"
                )
                if st.button("💾 저장", key="save_eq"):
                    if save_sheet('equipment', df_eq_edit):
                        st.success("완료!")
                        st.rerun()
        
        with at2:
            st.warning("⚠️ 직접 수정 주의")
            df_bk_edit = st.data_editor(
                load_sheet_cached('bookings'),
                num_rows="dynamic",
                use_container_width=True,
                key="bk_ed"
            )
            if st.button("💾 저장"):
                if save_sheet('bookings', df_bk_edit):
                    add_log("ADMIN", "관리자", "예약 수정")
                    st.success("완료!")
        
        with at3:
            st.warning("⚠️ 직접 수정 주의")
            df_wt_edit = st.data_editor(
                load_sheet_cached('water'),
                num_rows="dynamic",
                use_container_width=True,
                key="wt_ed"
            )
            if st.button("💾 저장", key="save_wt"):
                if save_sheet('water', df_wt_edit):
                    add_log("ADMIN", "관리자", "3차수 수정")
                    st.success("완료!")
        
        with at4:
            st.markdown("#### 📜 로그")
            try:
                df_logs = load_sheet_cached('logs')
                if not df_logs.empty and 'timestamp' in df_logs.columns:
                    df_logs_sorted = df_logs.sort_values(by='timestamp', ascending=False)
                    st.dataframe(df_logs_sorted, use_container_width=True)
                else:
                    st.info("📋 로그 없음")
            except Exception as e:
                st.warning("⚠️ 로그 로드 실패")
                st.caption(str(e))
    elif admin_pw:
        st.error("❌ 비밀번호 틀림")

st.divider()
st.caption("🔬 v2.1 | Rate Limit 최적화")