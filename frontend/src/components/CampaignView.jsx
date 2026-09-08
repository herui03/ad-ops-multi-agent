import React from 'react';
import { Calendar, DollarSign, Eye, MousePointerClick, Target } from 'lucide-react';

export default function CampaignView({ campaign }) {
  if (!campaign) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        Select a campaign
      </div>
    );
  }

  return (
    <div className="p-6 overflow-y-auto">
      <h2 className="text-lg font-bold text-gray-800 mb-1">
        {campaign.campaign_name || 'Campaign Details'}
      </h2>
      <p className="text-sm text-gray-500 mb-6">{campaign.objective}</p>
      <div className="grid grid-cols-2 gap-4 mb-6">
        <Metric icon={DollarSign} label="Total Budget" value={`¥${campaign.budget?.total_cny?.toLocaleString() || '—'}`} />
        <Metric icon={Calendar} label="Flight Dates" value={`${campaign.schedule?.start || '—'} ~ ${campaign.schedule?.end || '—'}`} />
        <Metric icon={Eye} label="Est. Impressions" value={campaign.estimated_performance?.impressions || '—'} />
        <Metric icon={MousePointerClick} label="Est. CTR" value={campaign.estimated_performance?.ctr || '—'} />
      </div>
      {campaign.placements && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <Target className="w-4 h-4" /> Placement Allocation
          </h3>
          <div className="space-y-2">
            {campaign.placements.map((p, i) => (
              <div key={i} className="bg-gray-50 rounded-lg p-3 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-800">{p.type}</p>
                  <p className="text-xs text-gray-500">{p.bid_type} · Bid ¥{p.suggested_bid}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-bold text-green-600">{p.budget_pct}%</p>
                  <p className="text-xs text-gray-400">of budget</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ icon: Icon, label, value }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-3 flex items-center gap-3">
      <div className="w-9 h-9 bg-gray-100 rounded-lg flex items-center justify-center">
        <Icon className="w-4 h-4 text-gray-500" />
      </div>
      <div>
        <p className="text-xs text-gray-400">{label}</p>
        <p className="text-sm font-semibold text-gray-800">{value}</p>
      </div>
    </div>
  );
}
