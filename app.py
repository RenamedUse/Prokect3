import dash
from dash import dcc, html, Input, Output, State
import plotly.graph_objs as go
import openmeteo_requests
import requests_cache
from retry_requests import retry
import requests

API_KEY = "311009e731663fbf64196b1959691d08"
BASE_URL_FORECAST = "https://api.openweathermap.org/data/2.5/forecast"
GEOCODE_URL = "http://api.openweathermap.org/geo/1.0/direct"

cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)


def get_coordinates(city):
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=ru&format=json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if "results" in data and len(data["results"]) > 0:
            latitude = data["results"][0]["latitude"]
            longitude = data["results"][0]["longitude"]
            return latitude, longitude
        else:
            raise ValueError(f"Не удалось найти координаты для города: {city}")
    except requests.exceptions.RequestException:
        raise ConnectionError("Ошибка подключения к серверу.")
    except ValueError as ve:
        raise ve


def get_weather_data(city):
    params = {
        'q': city,
        'appid': API_KEY,
        'units': 'metric'
    }
    try:
        response = requests.get(BASE_URL_FORECAST, params=params, timeout=5)
        response.raise_for_status()
        forecast_data = response.json()
        return forecast_data['list']
    except Exception as e:
        print(f"Ошибка получения данных для {city}: {e}")
        return []


app = dash.Dash(__name__)
app.title = "Прогноз погоды для маршрута"

app.layout = html.Div([
    html.H1("Прогноз погоды для маршрута", className='header'),

    html.Div([
        html.Label("Введите города на пути маршрута:", className='label'),
        dcc.Input(id='start-point', type='text', placeholder="Начальная точка", className='input'),
        dcc.Input(id='end-point', type='text', placeholder="Конечная точка", className='input'),
        html.Button('Добавить промежуточную точку', id='add-stop-btn', n_clicks=0, className='button'),
        html.Div(id='intermediate-stops', children=[], style={'marginTop': '20px'})
    ], style={'marginBottom': '20px', 'display': 'flex', 'gap': '50px'}),  # Увеличено расстояние между элементами

    html.Div([
        html.Label("Выберите интересующие параметры прогноза:", className='label'),
        dcc.Dropdown(
            id='parameter-dropdown',
            options=[
                {'label': 'Температура', 'value': 'temp'},
                {'label': 'Скорость ветра', 'value': 'wind'},
                {'label': 'Осадки', 'value': 'rain'}
            ],
            value=['temp'],
            multi=True,
            style={'backgroundColor': '#ffffff', 'color': '#000000'}
        ),
        dcc.RadioItems(
            id='interval-selector',
            options=[
                {'label': '1 день', 'value': 1},
                {'label': '3 дня', 'value': 3},
                {'label': '5 дней', 'value': 5}
            ],
            value=1,
            inline=True,
            style={'color': '#000000'}
        )
    ], style={'marginBottom': '30px'}),

    html.Button('Получить прогноз', id='submit-btn', n_clicks=0, className='button'),

    html.Div([
        html.H3("Заданный маршрут на карте", className='header'),
        dcc.Graph(id='map-graph', style={'height': '510px'})
    ], style={
        'marginTop': '20px',
        'border': '2px solid #FF6A00',
        'borderRadius': '10px',
        'padding': '30px',
        'backgroundColor': '#ffffff'
    }),

    html.Div(id='weather-output')
], style={'backgroundColor': '#ffffff'})


@app.callback(
    Output('intermediate-stops', 'children'),
    [Input('add-stop-btn', 'n_clicks')],
    [State('intermediate-stops', 'children')]
)
def add_intermediate_stop(n_clicks, children):
    if n_clicks > 0:
        new_input = dcc.Input(
            type='text',
            placeholder=f"Промежуточная точка {len(children) + 1}",
            id={'type': 'stop', 'index': len(children)},
            className='input'
        )
        children.append(new_input)
    return children


@app.callback(
    [Output('map-graph', 'figure'),
     Output('weather-output', 'children')],
    [Input('submit-btn', 'n_clicks')],
    [State('start-point', 'value'),
     State('end-point', 'value'),
     State('intermediate-stops', 'children'),
     State('parameter-dropdown', 'value'),
     State('interval-selector', 'value')]
)
def update_map_and_weather(n_clicks, start, end, stops, parameters, interval):
    if n_clicks == 0 or not start or not end:
        return go.Figure(), "Введите точки маршрута и нажмите ‘Получить прогноз’."

    route = [start] + [child['props']['value'] for child in stops if child['props']['value']] + [end]
    map_markers = []
    weather_data = {}
    latitudes = []
    longitudes = []
    cities_display = []

    for city in route:
        lat, lon = get_coordinates(city)
        if lat is None or lon is None:
            continue
        forecasts = get_weather_data(city)[:8 * interval]
        if not forecasts:
            continue
        weather_data[city] = forecasts
        latitudes.append(lat)
        longitudes.append(lon)
        cities_display.append(city)

    map_fig = go.Figure()

    map_fig.add_trace(go.Scattermapbox(
        lat=latitudes,
        lon=longitudes,
        mode='markers+lines',
        marker=go.scattermapbox.Marker(
            size=14,
            color='#FF6A00'
        ),
        text=cities_display,
        hoverinfo='text',
        name='Маршрут'
    ))

    map_fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_zoom=5,
        mapbox_center={"lat": latitudes[0], "lon": longitudes[0]},
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        plot_bgcolor='#ffffff'
    )

    elements = []
    for city, forecasts in weather_data.items():
        times = [item['dt_txt'] for item in forecasts]

        traces = []

        for param in parameters:
            if param == "temp":
                values = [item['main']['temp'] for item in forecasts]
                y_label = "Температура (°C)"
                line_color = "#FF6A00"

            elif param == "wind":
                values = [item['wind']['speed'] for item in forecasts]
                y_label = "Скорость ветра (м/с)"
                line_color = "#00A3E0"

            elif param == "rain":
                values = [item.get('rain', {}).get('3h', 0) for item in forecasts]
                y_label = "Осадки (мм)"
                line_color = "#00FF00"

            else:
                continue

            traces.append(go.Scatter(
                x=times,
                y=values,
                mode="lines+markers",
                name=param.capitalize(),
                hoverinfo="x+y",
                line=dict(color=line_color)
            ))

        elements.append(dcc.Graph(
            figure={
                "data": traces,
                "layout": go.Layout(
                    title=f"Прогноз для {city}",
                    xaxis_title="Время",
                    yaxis_title="Значения",
                    template="plotly_white",
                    hovermode="closest",
                    legend_title="Параметры",
                    plot_bgcolor="#ffffff",
                    paper_bgcolor="#ffffff"
                )
            }
        ))

    if not elements:
        elements.append("Нет доступных данных для отображения.")

    return map_fig, elements


if __name__ == '__main__':
    app.run_server(debug=False)
