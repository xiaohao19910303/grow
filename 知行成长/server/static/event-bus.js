/* Global event bus for cross-tab data synchronization */
(() => {
  'use strict';

  const listeners = new Map();

  const EventBus = {
    on(event, callback) {
      if (!listeners.has(event)) {
        listeners.set(event, new Set());
      }
      listeners.get(event).add(callback);

      // Return unsubscribe function
      return () => {
        const set = listeners.get(event);
        if (set) {
          set.delete(callback);
          if (set.size === 0) listeners.delete(event);
        }
      };
    },

    emit(event, data) {
      const set = listeners.get(event);
      if (set) {
        set.forEach(callback => {
          try {
            callback(data);
          } catch (error) {
            console.error(`EventBus error in ${event} handler:`, error);
          }
        });
      }
    },

    off(event, callback) {
      const set = listeners.get(event);
      if (set) {
        if (callback) {
          set.delete(callback);
          if (set.size === 0) listeners.delete(event);
        } else {
          listeners.delete(event);
        }
      }
    }
  };

  window.EventBus = EventBus;
})();
