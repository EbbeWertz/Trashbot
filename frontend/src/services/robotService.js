import { reactive, readonly } from 'vue';
import { io } from 'socket.io-client';

// --- Private State ---
const state = reactive({
  connected: false,
  uptime: '00:00:00',
  sensors: {
    motor_a: 0,
    motor_b: 0,
  },
  lastError: null
});

const socket = io({
  reconnectionAttempts: 5,
  timeout: 10000,
});

socket.on('connect', () => {
  state.connected = true;
  state.lastError = null;
});

socket.on('disconnect', () => {
  state.connected = false;
});

socket.on('connect_error', (err) => {
  state.lastError = `Connection failed: ${err.message}`;
  alert(state.lastError);
  state.connected = false;
});

socket.on('uptime_update', (value) => {
  state.uptime = value;
});

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