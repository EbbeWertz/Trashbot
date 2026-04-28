<template>
  <div class="h-screen flex flex-col p-4 bg-[#0f172a] text-slate-200">
    
    <AppHeader />

    <nav class="flex gap-2 mb-4">
      <router-link 
        v-for="tab in tabs" 
        :key="tab.id" 
        :to="tab.path"
        v-slot="{ isActive }"
        class="flex-auto"
      >
        <button 
          :class="isActive ? 'bg-blue-600 text-white shadow-lg' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'"
          class="w-full py-3 px-4 rounded-xl text-xs font-ui font-bold transition-all uppercase tracking-widest"
        >
          <i :class="tab.icon" class="mr-2"></i> {{ tab.label }}
        </button>
      </router-link>
    </nav>

    <main class="flex-1 relative overflow-hidden">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import AppHeader from './components/AppHeader.vue';
// import { useRobotService } from './services/robotService';

// const { connection, emergencyStop } = useRobotService();

const tabs = [
  { id: 'manual', label: 'Drive', icon: 'fas fa-gamepad', path: '/' },
  { id: 'gesture', label: 'Follow', icon: 'fas fa-hand-paper', path: '/follow' },
  { id: 'catch', label: 'Catch', icon: 'fas fa-basketball-ball', path: '/catch' },
  { id: 'config', label: 'Config', icon: 'fas fa-cog', path: '/config' }
];
</script>

<style>
/* Page Transition Logic */
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>