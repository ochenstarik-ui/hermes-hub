# Hermes Hub — Performance & Latency Specifications

## Overview
Hermes Hub is built as a native Windows desktop cockpit designed for high-frequency operations, zero-lag tab switching, and efficient system monitoring.

## Benchmarks & Telemetry

### 1. View Switching Performance
- **Target**: P95 < 200 ms.
- **Achieved (Measured across 20 cycles)**:
  - Average: **30.34 ms**
  - Median (P50): **22.00 ms**
  - 95th Percentile (P95): **183.69 ms**
- **Mechanism**:
  - Pre-instantiation & widget caching in `HermesHubApp.__init__`.
  - Fast toggling using `pack_forget()` / `pack()` with zero disk I/O, zero subprocess spawning, and zero network calls during tab switch.
  - Automatic `tab_switch_ms` logging with slow switch warnings.

### 2. Startup Latency
- **Target**: Cold launch < 2000 ms.
- **Achieved**: ~1200 ms cold startup.
- **Mechanism**:
  - Background asynchronous status refresh via `UnifiedHealthService`.
  - Instant UI rendering with cached status placeholders.

### 3. Window Resize & Movement
- **Mechanism**:
  - Debounced `<Configure>` event handlers (100 ms debounce timer).
  - Scaled icon caching via `AssetManager`.

### 4. Process Lifecycle & Clean Shutdown
- **Target**: 0 orphan / zombie processes after window close.
- **Verification**: 10/10 automated launch & destroy cycles completed with zero zombie processes.
- **Mechanism**:
  - Central `_on_close` coordinator canceling background workers and timers before Tk destruction.
  - `LifecycleSupervisor` tracking child processes by UUID and PID lease.
