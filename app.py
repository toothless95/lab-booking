import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
import altair as alt

# ---------------------------------------------------------
# 1. 설정 및 초기화
# ---------------------------------------------------------
st.set_page_config(page_title="실험실 통합 예약 시스템", layout="wide", page_icon="🔬")

# 데이터 파일 경로 정의
FILES = {
    'bookings': 'bookings.csv',
    'water': 'water_usage.csv',
    'logs': 'system_logs.csv',
    'labs': 'labs.csv',          
    'equipment': 'equipment.csv' 
}

ADMIN_PASSWORD = "admin1234"

# ---------------------------------------------------------
# 2. 데이터 처리 및 헬퍼 함수
# ---------------------------------------------------------
def load_data(file_key):
    # 파일이 없으면 기본 데이터 생성
    if not os.path.exists(FILES[file_key]):
        if file_key == 'labs':
            df = pd.DataFrame({'name': ['Lab1', 'Lab2', 'Lab3', 'Lab4', 'Lab5']})
            df.to_csv(FILES[file_key], index=False)
            return df
        elif file_key == 'equipment':
            df = pd.DataFrame({'name': [
                'ChemiDoc (케미닥)', 'CleanBench #1', 'CleanBench #2', 
                'CleanBench #3', 'CleanBench #4', 'CleanBench #5'
            ]})
            df.to_csv(FILES[file_key], index=False)
            return df
        else:
            return pd.DataFrame()
    
    return pd.read_csv(FILES[file_key], dtype=str)

def save_data(file_key, df):
    df.to_csv(FILES[file_key], index=False)

def add_log(action, user, details):
    df_log = load_data('logs')
    new_log = pd.DataFrame([{
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'action': action,
        'user': user,
        'details': details
    }])
    df_log = pd.concat([df_log, new_log], ignore_index=True)
    save_data('logs', df_log)

def parse_time(time_str):
    if not time_str or len(time_str) != 4 or not time_str.isdigit():
        return None
    hour = int(time_str[:2])
    minute = int(time_str[2:])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"

# 시간 차이 계산 (Duration)
def calculate_hours(start_str, end_str):
    try:
        if end_str == "24:00": end_minutes = 24 * 60
        else:
            eh, em = map(int, end_str.split(':'))
            end_minutes = eh * 60 + em
        
        sh, sm = map(int, start_str.split(':'))
        start_minutes = sh * 60 + sm
        return (end_minutes - start_minutes) / 60.0
    except:
        return 0.0

# 예약 중복 확인 함수
def check_overlap(df, date_str, eq_name, start_time, end_time, exclude_id=None):
    if df.empty: return False, ""
    df_check = df.copy()
    if exclude_id: df_check = df_check[df_check['id'] != exclude_id]

    df_check['start_time'] = df_check['start_time'].astype(str).str.slice(0, 5)
    df_check['end_time'] = df_check['end_time'].astype(str).str.slice(0, 5)
    
    same_day = df_check[(df_check['date'] == date_str) & (df_check['equipment'] == eq_name)]
    
    for idx, row in same_day.iterrows():
        if (row['start_time'] < end_time) and (row['end_time'] > start_time):
            return True, row['user_name']
    return False, ""

# 이름 일괄 변경 함수
def batch_rename(target_type, old_name, new_name):
    file_key = 'labs' if target_type == 'lab' else 'equipment'
    df_master = load_data(file_key)
    
    if old_name in df_master['name'].values:
        df_master.loc[df_master['name'] == old_name, 'name'] = new_name
        save_data(file_key, df_master)
    
    df_bookings = load_data('bookings')
    if not df_bookings.empty:
        col_name = 'lab' if target_type == 'lab' else 'equipment'
        if col_name in df_bookings.columns:
            mask = df_bookings[col_name] == old_name
            if mask.sum() > 0:
                df_bookings.loc[mask, col_name] = new_name
                save_data('bookings', df_bookings)
    
    if target_type == 'lab':
        df_water = load_data('water')
        if not df_water.empty:
            mask_w = df_water['lab'] == old_name
            if mask_w.sum() > 0:
                df_water.loc[mask_w, 'lab'] = new_name
                save_data('water', df_water)
    return True

# --- [동적 데이터 로드 및 색상 고정] ---
df_labs_list = load_data('labs')
LABS = df_labs_list['name'].tolist() if not df_labs_list.empty else []

df_eq_list = load_data('equipment')
EQUIPMENT = df_eq_list['name'].tolist() if not df_eq_list.empty else []

if LABS:
    lab_scale = alt.Scale(domain=LABS, scheme='tableau20')
else:
    lab_scale = alt.Scale(scheme='tableau20')

# ---------------------------------------------------------
# 3. UI 및 기능 구현
# ---------------------------------------------------------

st.title("🔬 5개 실험실 공동 기기 예약 시스템")

tab1, tab2, tab3, tab4 = st.tabs(["📅 예약 하기", "📊 전체 타임라인", "💧 3차수 사용량", "👮 관리자 모드"])

# --- [TAB 1] 기기 예약 ---
with tab1:
    col1, col2 = st.columns([1, 1.2])
    
    with col1:
        st.subheader("📝 새 예약 작성")
        if not LABS or not EQUIPMENT:
            st.error("관리자 모드에서 실험실 및 기기를 먼저 등록해주세요.")
        else:
            user_name = st.text_input("사용자 이름", placeholder="예: 홍길동")
            user_lab = st.selectbox("소속 실험실", LABS)
            st.divider()
            date = st.date_input("날짜 선택", datetime.now())
            eq_name = st.selectbox("사용 기기", EQUIPMENT)
            
            st.write("---")
            st.write("⏱️ **시간 입력** (예: 13시 30분 → 1330)")
            st.info("🌙 **오버나이트 예약:** 2300 ~ 0300 입력 시, **오늘 밤 11시부터 내일 새벽 3시**로 자동 예약됩니다.")
            
            t_col1, t_col2 = st.columns(2)
            start_str = t_col1.text_input("시작 시간", placeholder="0900", max_chars=4)
            end_str = t_col2.text_input("종료 시간", placeholder="1000", max_chars=4)
            password = st.text_input("비밀번호 (4자리 숫자)", type="password", max_chars=4, placeholder="삭제/수정용")
            
            if st.button("예약 등록하기", type="primary", use_container_width=True):
                formatted_start = parse_time(start_str)
                formatted_end = parse_time(end_str)
                
                if not user_name or len(password) != 4:
                    st.error("이름과 4자리 비밀번호를 정확히 입력해주세요.")
                elif not formatted_start or not formatted_end:
                    st.error("시간 형식이 잘못되었습니다.")
                else:
                    df = load_data('bookings')
                    is_overnight = formatted_end < formatted_start
                    
                    if is_overnight:
                        next_date = date + timedelta(days=1)
                        date_str1 = str(date)
                        date_str2 = str(next_date)
                        
                        overlap1, user1 = check_overlap(df, date_str1, eq_name, formatted_start, "24:00")
                        overlap2, user2 = check_overlap(df, date_str2, eq_name, "00:00", formatted_end)
                        
                        if overlap1: st.error(f"❌ 오늘 밤 예약 충돌! ({user1}님)")
                        elif overlap2: st.error(f"❌ 내일 새벽 예약 충돌! ({user2}님)")
                        else:
                            base_id = datetime.now().strftime('%Y%m%d%H%M%S')
                            new_data = pd.DataFrame([
                                {'id': base_id+"_1", 'user_name': user_name, 'lab': user_lab, 'equipment': eq_name, 'date': date_str1, 'start_time': formatted_start, 'end_time': "24:00", 'password': password},
                                {'id': base_id+"_2", 'user_name': user_name, 'lab': user_lab, 'equipment': eq_name, 'date': date_str2, 'start_time': "00:00", 'end_time': formatted_end, 'password': password}
                            ])
                            df = pd.concat([df, new_data], ignore_index=True)
                            save_data('bookings', df)
                            add_log("예약(Overnight)", user_name, f"{eq_name} / {formatted_start}~{formatted_end}")
                            st.success("🌙 오버나이트 예약 완료!")
                            st.rerun()
                    else:
                        if formatted_start == formatted_end: st.error("시간 확인 필요")
                        else:
                            overlap, overlap_user = check_overlap(df, str(date), eq_name, formatted_start, formatted_end)
                            if overlap: st.error(f"❌ 예약 충돌! ({overlap_user}님)")
                            else:
                                new_data = pd.DataFrame([{
                                    'id': datetime.now().strftime('%Y%m%d%H%M%S'),
                                    'user_name': user_name, 'lab': user_lab, 'equipment': eq_name, 
                                    'date': str(date), 'start_time': formatted_start, 'end_time': formatted_end, 'password': password
                                }])
                                df = pd.concat([df, new_data], ignore_index=True)
                                save_data('bookings', df)
                                add_log("예약 생성", user_name, f"{eq_name} / {str(date)} {formatted_start}~{formatted_end}")
                                st.success("예약 완료!")
                                st.rerun()

    with col2:
        # 타임라인
        df_current = load_data('bookings')
        if not df_current.empty:
            df_current = df_current[(df_current['date'] == str(date)) & (df_current['equipment'] == eq_name)]
        
        st.markdown(f"### 📊 {date} <br> {eq_name} 점유 현황", unsafe_allow_html=True)
        
        if not df_current.empty:
            chart_df = df_current.copy()
            chart_df['start_time'] = chart_df['start_time'].astype(str).str.slice(0, 5)
            chart_df['end_time'] = chart_df['end_time'].astype(str).str.slice(0, 5)
            chart_df['end_time_viz'] = chart_df['end_time'].replace("24:00", "23:59")
            chart_df['Start'] = pd.to_datetime(chart_df['date'].astype(str) + ' ' + chart_df['start_time'], format='%Y-%m-%d %H:%M')
            chart_df['End'] = pd.to_datetime(chart_df['date'].astype(str) + ' ' + chart_df['end_time_viz'], format='%Y-%m-%d %H:%M')
        else:
            chart_df = pd.DataFrame(columns=['Start', 'End', 'user_name', 'lab'])

        domain_start = pd.to_datetime(f"{date} 00:00:00")
        domain_end = pd.to_datetime(f"{date} 23:59:59")
        
        timeline = alt.Chart(chart_df).mark_bar(cornerRadius=5).encode(
            x=alt.X('user_name', title='예약자', axis=alt.Axis(labels=True)),
            y=alt.Y('Start', scale=alt.Scale(domain=[domain_start, domain_end]), axis=alt.Axis(format='%H:%M', tickCount=24), title='시간'),
            y2='End',
            color=alt.Color('lab', title='실험실', scale=lab_scale),
            tooltip=[
                'user_name', 
                'lab', 
                alt.Tooltip('start_time', type='nominal', title='시작'), 
                alt.Tooltip('end_time', type='nominal', title='종료')
            ]
        ).properties(height=600, width='container')
        st.altair_chart(timeline, use_container_width=True)

        # 나의 예약 관리
        st.divider()
        st.subheader(f"🔧 예약 관리 ({eq_name})")
        st.caption("현재 시간 이후의 예약만 표시됩니다.")
        
        df_bookings = load_data('bookings')
        if not df_bookings.empty:
            df_bookings = df_bookings[df_bookings['equipment'] == eq_name]
            if not df_bookings.empty:
                df_bookings['start_time'] = df_bookings['start_time'].astype(str).str.slice(0, 5)
                df_bookings['end_time'] = df_bookings['end_time'].astype(str).str.slice(0, 5)
                
                current_now = datetime.now()
                future_bookings = []
                for idx, row in df_bookings.iterrows():
                    check_time = row['end_time'] if row['end_time'] != "24:00" else "23:59"
                    if datetime.strptime(f"{row['date']} {check_time}", "%Y-%m-%d %H:%M") >= current_now:
                        future_bookings.append(row)
                
                if future_bookings:
                    df_future = pd.DataFrame(future_bookings).sort_values(by=['date', 'start_time'])
                    for index, row in df_future.iterrows():
                        display_time = f"{row['start_time']} ~ {row['end_time']}"
                        if row['end_time'] == "24:00": display_time += " (자정)"
                        if row['start_time'] == "00:00": display_time += " (자정)"
                        
                        with st.expander(f"📅 {row['date']} | 👤 {row['user_name']} | ⏰ {display_time}"):
                            st.write(f"🏢 **{row['lab']}**")
                            col_a, col_b = st.columns([2, 1])
                            pw = col_a.text_input("비밀번호", type="password", key=f"pw_{row['id']}")
                            
                            c1, c2 = st.columns(2)
                            ns = c1.text_input("새 시작", value=row['start_time'].replace(":",""), max_chars=4, key=f"ns_{row['id']}")
                            ne = c2.text_input("새 종료", value=row['end_time'].replace(":","").replace("2400","0000"), max_chars=4, key=f"ne_{row['id']}")
                            
                            b1, b2 = st.columns(2)
                            if b1.button("수정", key=f"mod_{row['id']}"):
                                if str(pw) == str(row['password']):
                                    fs, fe = parse_time(ns), parse_time(ne)
                                    if fs and fe and fs <= fe:
                                        df_all = load_data('bookings')
                                        df_all.loc[df_all['id'] == row['id'], 'start_time'] = fs
                                        df_all.loc[df_all['id'] == row['id'], 'end_time'] = fe
                                        save_data('bookings', df_all)
                                        st.success("수정 완료"); st.rerun()
                                else: st.error("비번 오류")
                            if b2.button("삭제", key=f"del_{row['id']}"):
                                if str(pw) == str(row['password']):
                                    df_all = load_data('bookings')
                                    df_all = df_all[df_all['id'] != row['id']]
                                    save_data('bookings', df_all)
                                    st.success("삭제 완료"); st.rerun()
                                else: st.error("비번 오류")
                else: st.info("향후 예약 없음")
            else: st.info("예약 없음")
        else: st.info("예약 없음")

# --- [TAB 2] 전체 타임라인 & 통계 ---
with tab2:
    st.subheader("🕑 기기별 24시간 전체 현황")
    target_date = st.date_input("날짜 선택", datetime.now(), key="timeline_date")
    
    df_viz = load_data('bookings')
    domain_start = pd.to_datetime(f"{target_date} 00:00:00")
    domain_end = pd.to_datetime(f"{target_date} 23:59:59")

    if not df_viz.empty:
        df_viz = df_viz[df_viz['date'] == str(target_date)]
        if not df_viz.empty:
            df_viz['start_time'] = df_viz['start_time'].astype(str).str.slice(0, 5)
            df_viz['end_time'] = df_viz['end_time'].astype(str).str.slice(0, 5)
            df_viz['end_time_viz'] = df_viz['end_time'].replace("24:00", "23:59")
            df_viz['start_dt'] = pd.to_datetime(df_viz['date'].astype(str) + ' ' + df_viz['start_time'], format='%Y-%m-%d %H:%M')
            df_viz['end_dt'] = pd.to_datetime(df_viz['date'].astype(str) + ' ' + df_viz['end_time_viz'], format='%Y-%m-%d %H:%M')
            
            chart = alt.Chart(df_viz).mark_bar().encode(
                x=alt.X('start_dt', title='시간', axis=alt.Axis(format='%H:%M', tickCount=24), scale=alt.Scale(domain=[domain_start, domain_end])),
                x2='end_dt', y=alt.Y('equipment', title='장비명'), color=alt.Color('lab', title='실험실', scale=lab_scale),
                tooltip=[
                    'user_name', 
                    'lab', 
                    alt.Tooltip('start_time', type='nominal', title='시작'), 
                    alt.Tooltip('end_time', type='nominal', title='종료')
                ]
            ).properties(height=400)
            st.altair_chart(chart, use_container_width=True)
        else: st.info("예약 없음")
    else: st.info("데이터 없음")

    st.divider()
    st.subheader("📈 기기별 사용 통계")
    stat_eq = st.selectbox("통계 기기 선택", EQUIPMENT) if EQUIPMENT else None
    
    if stat_eq:
        df_stats = load_data('bookings')
        if not df_stats.empty:
            df_stats = df_stats[df_stats['equipment'] == stat_eq]
            if not df_stats.empty:
                df_stats['duration'] = df_stats.apply(lambda x: calculate_hours(x['start_time'], x['end_time']), axis=1)
                df_stats['date_dt'] = pd.to_datetime(df_stats['date'])
                df_stats['month'] = df_stats['date_dt'].dt.strftime('%Y-%m')
                
                c1, c2 = st.columns(2)
                with c1:
                    cur_mon = datetime.now().strftime('%Y-%m')
                    st.markdown(f"#### 📅 {cur_mon} 점유율")
                    df_this = df_stats[df_stats['month'] == cur_mon]
                    if not df_this.empty:
                        pie_data = df_this.groupby('lab')['duration'].sum().reset_index()
                        pie_data['percent'] = pie_data['duration'] / pie_data['duration'].sum()
                        base = alt.Chart(pie_data).encode(theta=alt.Theta("duration", stack=True))
                        pie = base.mark_arc(innerRadius=60).encode(color=alt.Color("lab", scale=lab_scale), order=alt.Order("duration", sort="descending"), tooltip=["lab", "duration", alt.Tooltip("percent", format=".1%")])
                        text = base.mark_text(radius=100).encode(text=alt.Text("percent", format=".1%"), order=alt.Order("duration", sort="descending"), color=alt.value("black"))
                        st.altair_chart(pie+text, use_container_width=True)
                    else: st.info("데이터 없음")
                with c2:
                    st.markdown("#### 📊 월별 추이")
                    bar_data = df_stats.groupby(['month', 'lab'])['duration'].sum().reset_index()
                    mon_totals = bar_data.groupby('month')['duration'].sum().reset_index()
                    mon_totals.columns = ['month', 'total']
                    bar_data = pd.merge(bar_data, mon_totals, on='month')
                    bar_data['percent'] = bar_data['duration'] / bar_data['total']
                    bar = alt.Chart(bar_data).mark_bar().encode(x='month', y='duration', color=alt.Color('lab', scale=lab_scale), tooltip=['month', 'lab', 'duration', alt.Tooltip('percent', format='.1%')]).properties(height=300)
                    st.altair_chart(bar, use_container_width=True)
        else: st.info(f"'{stat_eq}'에 대한 예약 데이터가 없습니다.")
    else: st.info("데이터가 없습니다.")

# --- [TAB 3] 3차수 사용량 ---
with tab3:
    col1, col2 = st.columns([1, 1.5])
    with col1:
        st.subheader("💧 사용량 기록")
        with st.form("water_form"):
            w_name = st.text_input("이름")
            w_lab = st.selectbox("실험실", LABS) if LABS else st.error("실험실 설정 필요")
            w_amount = st.number_input("사용량 (L)", min_value=0.1, step=0.5)
            if st.form_submit_button("기록 저장"):
                df_w = load_data('water')
                new_w = pd.DataFrame([{'date': datetime.now().strftime('%Y-%m-%d'), 'user_name': w_name, 'lab': w_lab, 'amount': str(w_amount)}])
                df_w = pd.concat([df_w, new_w], ignore_index=True)
                save_data('water', df_w)
                add_log("3차수", w_name, f"{w_amount}L")
                st.success("저장됨"); st.rerun()
        st.divider(); st.write("📋 최근 기록"); df_w = load_data('water')
        if not df_w.empty: st.dataframe(df_w.tail(5))

    with col2:
        st.subheader("📊 통계 대시보드")
        if not df_w.empty:
            df_w['amount'] = pd.to_numeric(df_w['amount'], errors='coerce')
            df_w['date_dt'] = pd.to_datetime(df_w['date'])
            df_w['month'] = df_w['date_dt'].dt.strftime('%Y-%m')
            
            cur_mon = datetime.now().strftime('%Y-%m')
            st.markdown(f"#### 📅 {cur_mon} 점유율")
            df_tm = df_w[df_w['month'] == cur_mon]
            if not df_tm.empty:
                ms = df_tm.groupby('lab')['amount'].sum().reset_index()
                ms['percent'] = ms['amount'] / ms['amount'].sum()
                base = alt.Chart(ms).encode(theta=alt.Theta("amount", stack=True))
                pie = base.mark_arc(innerRadius=60).encode(color=alt.Color("lab", scale=lab_scale), order=alt.Order("amount", sort="descending"), tooltip=["lab", "amount", alt.Tooltip("percent", format=".1%")])
                text = base.mark_text(radius=100).encode(text=alt.Text("percent", format=".1%"), order=alt.Order("amount", sort="descending"), color=alt.value("black"))
                st.altair_chart(pie+text, use_container_width=True)
            else: st.info("데이터 없음")
            
            st.divider(); st.markdown("#### 📈 월별 추이")
            m_stats = df_w.groupby(['month', 'lab'])['amount'].sum().reset_index()
            m_tots = m_stats.groupby('month')['amount'].sum().reset_index()
            m_tots.columns = ['month', 'total']
            m_stats = pd.merge(m_stats, m_tots, on='month')
            m_stats['percent'] = m_stats['amount'] / m_stats['total']
            bar = alt.Chart(m_stats).mark_bar().encode(x='month', y='amount', color=alt.Color('lab', scale=lab_scale), tooltip=['month', 'lab', 'amount', alt.Tooltip('percent', format='.1%')]).properties(height=350)
            st.altair_chart(bar, use_container_width=True)

# --- [TAB 4] 관리자 모드 ---
with tab4:
    st.subheader("👮 관리자 페이지 (Super Admin)")
    admin_input = st.text_input("관리자 비밀번호", type="password")
    
    if admin_input == ADMIN_PASSWORD:
        st.success("관리자 권한 승인됨 ✅")
        adm_tab1, adm_tab2, adm_tab3, adm_tab4 = st.tabs([
            "⚙️ 설정 (랩/기기)", "📅 예약 데이터 수정", "💧 3차수 데이터 수정", "📜 시스템 로그"
        ])
        
        with adm_tab1:
            col_set1, col_set2 = st.columns(2)
            with col_set1:
                st.markdown("#### 🧪 실험실 목록 관리")
                df_lab_edit = st.data_editor(load_data('labs'), num_rows="dynamic", key="editor_labs")
                if st.button("실험실 목록 저장"):
                    save_data('labs', df_lab_edit)
                    st.success("목록 저장됨")
                
                st.markdown("---")
                with st.expander("🛠️ 실험실 이름 일괄 변경"):
                    old_lab_name = st.selectbox("변경할 실험실", LABS, key="old_lab")
                    new_lab_name = st.text_input("새 이름", key="new_lab")
                    if st.button("실험실 변경 적용"):
                        if not new_lab_name:
                            st.error("새 이름을 입력하세요.")
                        elif new_lab_name in LABS:
                            st.error("❌ 이미 존재하는 이름입니다!")
                        else:
                            batch_rename('lab', old_lab_name, new_lab_name)
                            add_log("ADMIN", "관리자", f"실험실 이름 변경: {old_lab_name}->{new_lab_name}")
                            st.success("변경 완료!"); st.rerun()

            with col_set2:
                st.markdown("#### 🔬 기기 목록 관리")
                df_eq_edit = st.data_editor(load_data('equipment'), num_rows="dynamic", key="editor_eq")
                if st.button("기기 목록 저장"):
                    save_data('equipment', df_eq_edit)
                    st.success("목록 저장됨")
                
                st.markdown("---")
                with st.expander("🛠️ 기기 이름 일괄 변경"):
                    old_eq_name = st.selectbox("변경할 기기", EQUIPMENT, key="old_eq")
                    new_eq_name = st.text_input("새 이름", key="new_eq")
                    if st.button("기기 변경 적용"):
                        if not new_eq_name:
                            st.error("새 이름을 입력하세요.")
                        elif new_eq_name in EQUIPMENT:
                            st.error("❌ 이미 존재하는 이름입니다!")
                        else:
                            batch_rename('equipment', old_eq_name, new_eq_name)
                            add_log("ADMIN", "관리자", f"기기 이름 변경: {old_eq_name}->{new_eq_name}")
                            st.success("변경 완료!"); st.rerun()

        with adm_tab2:
            st.markdown("#### 📅 전체 예약 내역")
            df_bookings_all = load_data('bookings')
            edited_bookings = st.data_editor(df_bookings_all, num_rows="dynamic", use_container_width=True, key="editor_bookings")
            if st.button("예약 저장"):
                save_data('bookings', edited_bookings)
                add_log("ADMIN", "관리자", "예약 강제 수정")
                st.success("저장됨")

        with adm_tab3:
            st.markdown("#### 💧 3차수 사용 기록")
            df_water_all = load_data('water')
            edited_water = st.data_editor(df_water_all, num_rows="dynamic", use_container_width=True, key="editor_water")
            if st.button("물 사용량 저장"):
                save_data('water', edited_water)
                add_log("ADMIN", "관리자", "3차수 강제 수정")
                st.success("저장됨")

        with adm_tab4:
            st.markdown("#### 📜 로그")
            df_logs = load_data('logs')
            if not df_logs.empty:
                st.dataframe(df_logs.sort_values(by='timestamp', ascending=False), use_container_width=True)
            else: st.info("로그 없음")