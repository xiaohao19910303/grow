## ADDED Requirements

### Requirement: Minute-level data playback
The system SHALL provide historical minute-level price data playback with K-line chart visualization for individual instruments.

#### Scenario: Load minute data
- **WHEN** user selects an instrument and date range for minute replay
- **THEN** system fetches minute-level OHLCV data from the data source and displays a K-line chart

#### Scenario: Chart display
- **WHEN** minute data is loaded
- **THEN** system displays a candlestick chart with price on Y-axis and time on X-axis, including volume bars below

#### Scenario: Time range selection
- **WHEN** user selects a specific trading date
- **THEN** system displays minute data for that date (approximately 240 minutes of trading: 9:30-11:30, 13:00-15:00)

### Requirement: Playback controls
The system SHALL provide playback controls allowing users to play, pause, step through, and adjust the speed of minute data playback.

#### Scenario: Play/pause playback
- **WHEN** user clicks "Play"
- **THEN** system automatically advances through minute data at 1x speed; clicking "Pause" stops the playback

#### Scenario: Step through data
- **WHEN** user clicks "Next" or "Previous"
- **THEN** system advances or rewinds by one minute, updating the chart display

#### Scenario: Playback speed adjustment
- **WHEN** user adjusts playback speed (0.5x, 1x, 2x, 4x)
- **THEN** system adjusts the playback interval accordingly

### Requirement: Technical indicator overlay
The system SHALL support overlaying common technical indicators on the minute K-line chart.

#### Scenario: Moving average overlay
- **WHEN** user enables MA (Moving Average) indicator
- **THEN** system calculates and overlays MA5, MA10, MA20 lines on the price chart

#### Scenario: Volume indicator
- **WHEN** user enables volume indicator
- **THEN** system displays volume bars below the price chart

#### Scenario: MACD indicator
- **WHEN** user enables MACD indicator
- **THEN** system calculates and displays MACD line, signal line, and histogram in a separate panel below the price chart

### Requirement: Data source and storage
The system SHALL fetch minute-level data from the configured data source and cache it in the database for efficient replay.

#### Scenario: Data fetching
- **WHEN** user requests minute data for an instrument
- **THEN** system first checks the database cache; if not available, fetches from the data source (Tushare/AKShare)

#### Scenario: Data caching
- **WHEN** minute data is fetched from the data source
- **THEN** system stores the data in the database for future replay, avoiding repeated API calls

#### Scenario: Data availability
- **WHEN** minute data is not available for a specific date (e.g., weekend, holiday, or data source limitation)
- **THEN** system displays a message indicating data is not available for that date

### Requirement: Interactive chart features
The system SHALL provide interactive chart features including zooming, panning, and crosshair for detailed analysis.

#### Scenario: Zoom in/out
- **WHEN** user uses mouse wheel or zoom controls
- **THEN** system zooms in or out on the time axis, showing more or fewer minutes

#### Scenario: Pan left/right
- **WHEN** user drags the chart left or right
- **THEN** system pans the view to show earlier or later minutes

#### Scenario: Crosshair display
- **WHEN** user hovers over the chart
- **THEN** system displays a crosshair with detailed information for that minute (open, high, low, close, volume)
