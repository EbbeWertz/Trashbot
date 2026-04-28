import { reactive, readonly } from 'vue';
import { io } from 'socket.io-client';

// --- Private State ---
const state = reactive({
  connected: false,
  uptime: '00:00:00',
  sensors: {
    battery: 0,
    temp: 0,
    distance: 0
  },
  lastError: null
});

// --- Socket Initialization ---
// Passing no URL works if hosted on the same IP/Port as the backend
const socket = io({
  reconnectionAttempts: 5,
  timeout: 10000,
});

// --- Internal Event Listeners ---
socket.on('connect', () => {
  state.connected = true;
  state.lastError = null;
});

socket.on('disconnect', () => {
  state.connected = false;
});

socket.on('connect_error', (err) => {
  state.lastError = `Connection failed: ${err.message}`;
});

// Cadence 1: The 1Hz Uptime Heartbeat
socket.on('uptime_update', (value) => {
  state.uptime = value;
});

// Cadence 2: The Async Sensor Push
socket.on('sensor_data', (data) => {
  Object.assign(state.sensors, data);
});

// --- Exported Methods ---
export function useRobot() {
  
  const sendDrive = (x, y) => {
    socket.emit('drive', { x, y });
  };

  const emergencyStop = () => {
    socket.emit('abort');
  };

  const updateConfig = (config) => {
    socket.emit('update_config', config);
  };

  return {
    // Readonly prevents components from accidentally mutating state directly
    status: readonly(state), 
    sendDrive,
    emergencyStop,
    updateConfig
  };
}