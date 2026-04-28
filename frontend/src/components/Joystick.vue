<template>
  <div class="glass rounded-3xl p-6 flex flex-col items-center">
    <h3 class="text-[10px] font-ui text-slate-500 uppercase tracking-widest mb-6">Directional Vector</h3>
    <div 
      class="joy-base w-64 h-64 relative flex items-center justify-center border-4 border-slate-800 shadow-inner"
      @touchstart="handleTouch" 
      @touchmove="handleTouch" 
      @touchend="resetJoy"
    >
      <div class="absolute w-full h-px bg-slate-800"></div>
      <div class="absolute h-full w-px bg-slate-800"></div>
      <div 
        class="joy-thumb w-20 h-20 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 shadow-2xl flex items-center justify-center border-4 border-blue-400/50 pointer-events-none"
        :style="{ transform: `translate(${joyPos.x}px, ${joyPos.y}px)` }"
      >
        <i class="fas fa-arrows-alt text-white/50"></i>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';

const emit = defineEmits(['move']);
const joyPos = ref({ x: 0, y: 0 });
const limit = 80;

const handleTouch = (e) => {
  const rect = e.currentTarget.getBoundingClientRect();
  const touch = e.touches[0];
  const centerX = rect.left + rect.width / 2;
  const centerY = rect.top + rect.height / 2;
  
  let dx = touch.clientX - centerX;
  let dy = touch.clientY - centerY;
  
  const distance = Math.sqrt(dx * dx + dy * dy);
  if (distance > limit) {
    dx *= limit / distance;
    dy *= limit / distance;
  }

  joyPos.value = { x: dx, y: dy };
  emit('move', { x: dx / limit, y: -dy / limit });
};

const resetJoy = () => {
  joyPos.value = { x: 0, y: 0 };
  emit('move', { x: 0, y: 0 });
};
</script>

<style scoped>
.joy-base { touch-action: none; border-radius: 50%; background: radial-gradient(circle, #1e293b 0%, #0f172a 100%); }
.joy-thumb { transition: transform 0.05s ease-out; }
</style>