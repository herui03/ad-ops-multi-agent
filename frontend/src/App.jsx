import React, { useState, useEffect, useCallback, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatPanel from './components/ChatPanel';
import Dashboard from './components/Dashboard';
import AgentStatus from './components/AgentStatus';
import HumanApproval from './components/HumanApproval';
import { createWebSocket, getDashboardStats } from './api';

function generateSessionId() {
  return 'sess_' + Math.random().toString(36).substring(2, 10);
}

export default function App() {
  const [activeView, setActiveView] = useState('chat');
  const [sessionId] = useState(generateSessionId);
  const [agentStatuses, setAgentStatuses] = useState({});
  const [pendingApprovals, setPendingApprovals] = useState([]);
  const [dashboardData, setDashboardData] = useState(null);
  const orchStartRef = useRef(null);

  // ── WebSocket is the single source of truth for agent status ──
  useEffect(() => {
    const socket = createWebSocket(sessionId, (data) => {

      if (data.type === 'agent_status') {
        const { agent, status, duration_ms } = data;

        if (agent === 'orchestrator' && status === 'planning') {
          // New request → reset all agent states, orchestrator goes active (blue)
          orchStartRef.current = Date.now();
          setAgentStatuses({ orchestrator: { status: 'planning', duration_ms: null } });

        } else if (status === 'running') {
          // Agent started → active (blue)
          setAgentStatuses(prev => ({
            ...prev,
            [agent]: { status: 'planning', duration_ms: null },
          }));

        } else if (status === 'completed') {
          // Agent finished → done (green)
          let ms = duration_ms || null;
          if (agent === 'orchestrator' && orchStartRef.current) {
            ms = Date.now() - orchStartRef.current;
            orchStartRef.current = null;
          }
          setAgentStatuses(prev => ({
            ...prev,
            [agent]: { status: 'completed', duration_ms: ms },
          }));

        } else if (status === 'failed') {
          setAgentStatuses(prev => ({
            ...prev,
            [agent]: { status: 'completed', duration_ms: null },
          }));
        }
        // synthesizing / direct_answer → no change, orchestrator stays active

      } else if (data.type === 'human_approval_required') {
        setPendingApprovals(prev => [...prev, ...data.approvals]);
      }
    });

    return () => socket.close();
  }, [sessionId]);

  useEffect(() => {
    if (activeView === 'dashboard') {
      getDashboardStats().then(setDashboardData).catch(console.error);
    }
  }, [activeView]);


  const handleApprovalsReceived = useCallback((approvals) => {
    setPendingApprovals(prev => [...prev, ...approvals]);
  }, []);

  const handleApprovalResolved = useCallback((id) => {
    setPendingApprovals(prev => prev.filter(a => a.approval_id !== id));
  }, []);

  return (
    <div className="flex h-screen bg-gray-100">
      <Sidebar activeView={activeView} onViewChange={setActiveView} pendingCount={pendingApprovals.length} />

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 flex flex-col overflow-hidden">
          <div
            className="flex-1 flex flex-col"
            style={{ display: activeView === 'chat' ? 'flex' : 'none' }}
          >
            <ChatPanel
              sessionId={sessionId}
              onApprovalsReceived={handleApprovalsReceived}
            />
          </div>
          <div
            className="flex-1 overflow-auto"
            style={{ display: activeView === 'dashboard' ? 'block' : 'none' }}
          >
            <Dashboard data={dashboardData} />
          </div>
        </div>

        <div className="w-80 border-l border-gray-200 bg-white flex flex-col overflow-y-auto">
          <AgentStatus statuses={agentStatuses} />
          {pendingApprovals.length > 0 && (
            <HumanApproval approvals={pendingApprovals} onResolved={handleApprovalResolved} />
          )}
        </div>
      </div>
    </div>
  );
}