import React from 'react';
import { MessageSquare, LayoutDashboard, Bot, Bell, Settings } from 'lucide-react';

export default function Sidebar({ activeView, onViewChange, pendingCount }) {
  return (
    <div className="w-16 bg-gray-900 flex flex-col items-center py-4 gap-2">
      <div className="w-10 h-10 bg-green-500 rounded-xl flex items-center justify-center mb-6">
        <Bot className="w-6 h-6 text-white" />
      </div>
      {[
        { id: 'chat', label: 'Chat', icon: MessageSquare },
        { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
      ].map(item => (
        <button
          key={item.id}
          onClick={() => onViewChange(item.id)}
          className={`w-12 h-12 rounded-xl flex items-center justify-center transition-colors ${
            activeView === item.id ? 'bg-green-600 text-white' : 'text-gray-400 hover:bg-gray-800 hover:text-white'
          }`}
          title={item.label}
        >
          <item.icon className="w-5 h-5" />
        </button>
      ))}
      <button
        className="w-12 h-12 rounded-xl flex items-center justify-center text-gray-400 hover:bg-gray-800 hover:text-white relative mt-auto"
        title="Notifications"
      >
        <Bell className="w-5 h-5" />
        {pendingCount > 0 && (
          <span className="absolute top-1 right-1 w-5 h-5 bg-red-500 text-white text-xs rounded-full flex items-center justify-center">
            {pendingCount}
          </span>
        )}
      </button>
      <button
        className="w-12 h-12 rounded-xl flex items-center justify-center text-gray-400 hover:bg-gray-800 hover:text-white"
        title="Settings"
      >
        <Settings className="w-5 h-5" />
      </button>
    </div>
  );
}
