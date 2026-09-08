import React from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts';
import { Users, Megaphone, DollarSign, TrendingUp, Activity } from 'lucide-react';

const COLORS = ['#07C160', '#1890ff', '#faad14', '#f5222d', '#722ed1', '#13c2c2'];

export default function Dashboard({ data }) {
  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400">
        Loading...
      </div>
    );
  }

  const agentChart = (data.agents || []).map(a => ({
    name: a.label,
    Calls: a.calls_today,
    Latency: a.avg_latency_ms,
  }));

  const spendPie = [
    { name: 'Moments Feed', value: 45 },
    { name: 'Channels', value: 28 },
    { name: 'Official Accounts', value: 15 },
    { name: 'Mini Programs', value: 8 },
    { name: 'Search', value: 4 },
  ];

  return (
    <div className="flex-1 overflow-y-auto bg-gray-50 p-6">
      <h1 className="text-xl font-bold text-gray-800 mb-6">System Dashboard</h1>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <KPI icon={Megaphone} label="Active Campaigns" value={data.active_campaigns} color="green" />
        <KPI icon={Users} label="Total Clients" value={data.total_clients} color="blue" />
        <KPI icon={DollarSign} label="Monthly Spend" value={`¥${(data.monthly_spend_cny / 1000).toFixed(0)}k`} color="yellow" />
        <KPI icon={TrendingUp} label="Avg ROAS" value={`${data.avg_roas}x`} color="purple" />
      </div>

      <div className="grid grid-cols-2 gap-4 mb-6">
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
            <Activity className="w-4 h-4" /> Agent Calls Today
          </h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={agentChart}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="Calls" fill="#07C160" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">Spend by Placement</h3>
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie
                data={spendPie}
                cx="50%" cy="50%"
                innerRadius={60} outerRadius={100}
                paddingAngle={2} dataKey="value"
                label={({ name, value }) => `${name} ${value}%`}
              >
                {spendPie.map((e, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-4">Agent Performance</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 text-gray-500">
              <th className="text-left py-2 font-medium">Agent</th>
              <th className="text-right py-2 font-medium">Calls Today</th>
              <th className="text-right py-2 font-medium">Avg Latency</th>
              <th className="text-right py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {(data.agents || []).map((a, i) => (
              <tr key={i} className="border-b border-gray-50">
                <td className="py-2.5 font-medium text-gray-800">{a.label}</td>
                <td className="py-2.5 text-right text-gray-600">{a.calls_today}</td>
                <td className="py-2.5 text-right text-gray-600">{a.avg_latency_ms}ms</td>
                <td className="py-2.5 text-right">
                  <span className="inline-flex items-center gap-1 text-green-600 text-xs">
                    <span className="w-1.5 h-1.5 bg-green-500 rounded-full" /> Online
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function KPI({ icon: Icon, label, value, color }) {
  const c = {
    green: 'bg-green-50 text-green-600',
    blue: 'bg-blue-50 text-blue-600',
    yellow: 'bg-yellow-50 text-yellow-600',
    purple: 'bg-purple-50 text-purple-600',
  };
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${c[color]}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div>
          <p className="text-xs text-gray-400">{label}</p>
          <p className="text-lg font-bold text-gray-800">{value}</p>
        </div>
      </div>
    </div>
  );
}