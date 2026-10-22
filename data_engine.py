import pandas as pd
import plotly.express as px

def analyze_records(source, temp_threshold=4.0):
    if hasattr(source, "seek"):
        source.seek(0)

    df = pd.read_csv(source)
    print(f"[DEBUG] Loaded columns: {list(df.columns)}")
    print(f"[DEBUG] Row count: {len(df)}")
    time_col = 'timestamps' if 'timestamps' in df.columns else 'timestamp'
    df['timestamp'] = pd.to_datetime(df[time_col])
    df = df.sort_values(by='timestamp')
    temp_col = next(
        (
            c
            for c in [
                'temp_celsius',
                'temp_celcius',
                'temperature',
                'temp',
                'ambient_temp',
            ]
            if c in df.columns
        ),
        None,
    )
    if not temp_col:
        raise KeyError(
            f"Could not locate a temperature column in: {list(df.columns)}"
        )
    if df[temp_col].dtype == object:
        clean_series = (
        df[temp_col].astype(str).str.strip().str.replace(r"[\[\]\'\"]", "", regex=True)
            )
        df['temp_celsius'] = pd.to_numeric(clean_series, errors='coerce')
    else:
        df['temp_celsius'] = pd.to_numeric(df[temp_col], errors='coerce')

    df_hot = df[df['temp_celsius'] > temp_threshold]
    summary = {
    "has_breach": not df_hot.empty,
    "breach_count": len(df_hot),
    "peak_temperature": df['temp_celsius'].max(),
            }

    if not df_hot.empty:
        start_time = df_hot['timestamp'].min()
        end_time = df_hot['timestamp'].max()
        duration_seconds = max((end_time - start_time).total_seconds(), 900)
        
        summary.update({
            "max_temperature": float(df_hot['temp_celsius'].max()),
            "breach_duration_minutes": round(duration_seconds / 60.0, 1),
            "breach_duration_hours": round(duration_seconds / 3600.0, 2),
            "first_breach_timestamp": start_time.strftime('%Y-%m-%d %H:%M:%S'),
            "last_breach_timestamp": end_time.strftime('%Y-%m-%d %H:%M:%S'),
            "power_fault_verified": bool(
                df_hot['power_status'].astype(str).str.contains('FAULT|STANDBY', case=False, na=False).any()
            ) if 'power_status' in df_hot.columns else False,
            "container_id": df.iloc[0]['container_id'],
        })
    fig = px.line(
                    df,
                    x='timestamp',
                    y='temp_celsius',
                    title='Temperature Over Time',
                    template='plotly_white',   # change template here
                    labels={'temp_celsius': 'Temperature (°C)', 'timestamp': 'Time'}
                )
    fig.add_hline(
                    y=temp_threshold,
                    line_dash='dash',
                    line_color='red',
                    line_width=2,
                    annotation_text=f"Threshold ({temp_threshold}°C)",
                    annotation_position='bottom right'
                )

    return df, summary, fig

if __name__ == "__main__":
    df, summary, fig = analyze_records("sample_readings.csv", temp_threshold=4.0)
    print("- Telemetry Analysis Results -")
    for key, value in summary.items():
        print(f"{key}: {value}")