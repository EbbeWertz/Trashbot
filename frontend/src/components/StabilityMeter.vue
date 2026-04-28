<template>
  <div class="glass p-6 rounded-3xl flex-1 flex flex-col items-center justify-center relative overflow-hidden">
    <h3 class="absolute top-4 left-6 text-[10px] font-ui text-slate-500 uppercase tracking-widest">Stability Index</h3>
    
    <div class="relative w-64 h-32 mt-6 overflow-hidden">
      <div class="absolute bottom-0 w-64 h-64 rounded-full border-[16px] border-slate-700/30"></div>
      
      <div class="tilt-hand absolute bottom-0 left-1/2 w-1.5 h-full bg-blue-400 origin-bottom rounded-full"
           :style="{ transform: `translateX(-50%) rotate(${tilt}deg)` }">
        <div class="w-4 h-4 bg-blue-400 rounded-full absolute top-0 -left-1.5 shadow-[0_0_10px_#60a5fa]"></div>
      </div>

      <div class="tilt-peak absolute bottom-0 left-1/2 w-1 h-full bg-red-400 origin-bottom rounded-full"
           :style="{ transform: `translateX(-50%) rotate(${peakTilt}deg)`, opacity: peakOpacity }"></div>
    </div>
    <div class="mt-4 font-ui text-2xl font-bold text-white">{{ tilt }}°</div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue';

const props = defineProps(['tilt']);
const peakTilt = ref(0);
const peakOpacity = ref(0);

watch(() => props.tilt, (newVal) => {
  if (Math.abs(newVal) > Math.abs(peakTilt.value)) {
    peakTilt.value = newVal;
    peakOpacity.value = 1;
    setTimeout(() => peakOpacity.value = 0, 1000);
    setTimeout(() => peakTilt.value = 0, 2500);
  }
});
</script>