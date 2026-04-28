<template>
  <header class="flex justify-between items-center glass rounded-2xl mb-2 shadow-2xl pb-2">
    <div class="flex items-center gap-4">
      <img src="/favicon.svg" alt="TrashBot Logo" class="w-12 h-12 object-contain" />
      <div>
        <h1 class="font-ui font-bold text-lg tracking-wider text-white">
          MTO <span class="text-blue-400">TRASHBOT</span>
        </h1>
        <div class="flex gap-3 text-[10px] text-slate-400 uppercase font-bold tracking-widest">
          <span>
            <i class="fas fa-wifi text-green-500 mr-1"></i> 
            {{ connection.socket }}
          </span>
          <span>
            <i class="fas fa-bolt text-yellow-500 mr-1"></i> 
            {{ connection.uptime }}
          </span>
        </div>
      </div>
    </div>
    
    <button 
      @click="$emit('abort')" 
      class="bg-red-500 hover:bg-red-600 text-white font-black px-6 py-3 rounded-xl shadow-lg active:scale-95 transition-all"
    >
      STOP (ESC)
    </button>
  </header>
  
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue';
defineProps({
  connection: {
    type: Object,
    default: () => ({ socket: 'connected', uptime: '00h 00m 00s' })
  }
});

const emit = defineEmits(['abort']);

const handleKeyDown = (event) => {
  if (event.key === 'Escape') {
    emit('abort');
  }
};

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown);
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown);
});

</script>