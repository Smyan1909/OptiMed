'use client';

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { Header } from '@/components/Header';
import { useState } from "react";
import { useUser } from '@/contexts/UserContext';
import { useLocale, useTranslations } from 'next-intl';
import { localeOptions } from '@/i18n/config';

function SettingsContent() {
  const { user } = useUser();
  const locale = useLocale();
  const t = useTranslations('settings');
  const [activeTab, setActiveTab] = useState('preferences');
  const [formData, setFormData] = useState({
    notifications: true,
    darkMode: false,
    language: locale
  });

  const tabs = [
    { id: 'preferences', name: t('tabs.preferences'), icon: '⚙️' },
    { id: 'notifications', name: t('tabs.notifications'), icon: '🔔' },
    { id: 'security', name: t('tabs.security'), icon: '🔒' }
  ];

  if (!user) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header />
        <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
          <div className="flex items-center justify-center h-64">
              <div className="text-center">
              <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
                <p className="text-gray-900 font-medium">{t('loading')}</p>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        <div className="px-4 py-6 sm:px-0">
          <div className="mb-8">
            <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
            <p className="mt-2 text-gray-600">{t('subtitle')}</p>
          </div>

          <div className="bg-white shadow rounded-lg overflow-hidden">
            {/* Tab Navigation */}
            <div className="border-b border-gray-200">
              <nav className="flex">
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex items-center space-x-2 px-6 py-4 text-sm font-medium border-b-2 transition-colors ${
                      activeTab === tab.id
                        ? 'border-blue-500 text-blue-600'
                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                    }`}
                  >
                    <span>{tab.icon}</span>
                    <span>{tab.name}</span>
                  </button>
                ))}
              </nav>
            </div>

            {/* Tab Content */}
            <div className="p-6">
              {/* Preferences Tab */}
              {activeTab === 'preferences' && (
                <div className="space-y-6">
                  <h3 className="text-lg font-medium text-gray-900">{t('preferences.title')}</h3>
                  
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <label className="text-sm font-medium text-gray-700">{t('preferences.darkMode.label')}</label>
                        <p className="text-sm text-gray-500">{t('preferences.darkMode.description')}</p>
                      </div>
                      <button
                        onClick={() => setFormData({...formData, darkMode: !formData.darkMode})}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                          formData.darkMode ? 'bg-blue-600' : 'bg-gray-200'
                        }`}
                      >
                        <span
                          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            formData.darkMode ? 'translate-x-6' : 'translate-x-1'
                          }`}
                        />
                      </button>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">{t('preferences.language.label')}</label>
                      <select
                        value={formData.language}
                        onChange={async (e) => {
                          const newLocale = e.target.value;
                          setFormData({...formData, language: newLocale});
                          try {
                            // Use redirect-capable endpoint to ensure a full reload
                            const currentPath = window.location.pathname + window.location.search;
                            const url = `/api/locale?locale=${encodeURIComponent(newLocale)}&redirect=${encodeURIComponent(currentPath)}`;
                            window.location.assign(url);
                          } catch {}
                        }}
                        className="w-full md:w-auto border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      >
                        {localeOptions.map((opt) => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                </div>
              )}

              {/* Notifications Tab */}
              {activeTab === 'notifications' && (
                <div className="space-y-6">
                  <h3 className="text-lg font-medium text-gray-900">{t('notifications.title')}</h3>
                  
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <label className="text-sm font-medium text-gray-700">{t('notifications.email.label')}</label>
                        <p className="text-sm text-gray-500">{t('notifications.email.description')}</p>
                      </div>
                      <button
                        onClick={() => setFormData({...formData, notifications: !formData.notifications})}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                          formData.notifications ? 'bg-blue-600' : 'bg-gray-200'
                        }`}
                      >
                        <span
                          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            formData.notifications ? 'translate-x-6' : 'translate-x-1'
                          }`}
                        />
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Security Tab */}
              {activeTab === 'security' && (
                <div className="space-y-6">
                  <h3 className="text-lg font-medium text-gray-900">{t('security.title')}</h3>
                  
                  <div className="space-y-6">
                    <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
                      <div className="flex">
                        <div className="flex-shrink-0">
                          <span className="text-yellow-400">⚠️</span>
                        </div>
                        <div className="ml-3">
                          <h4 className="text-sm font-medium text-yellow-800">{t('security.password.title')}</h4>
                          <p className="mt-1 text-sm text-yellow-700">{t('security.password.description')}</p>
                        </div>
                      </div>
                    </div>

                    <div className="border border-gray-200 rounded-lg p-4">
                      <h4 className="text-sm font-medium text-gray-700 mb-3">{t('security.session.title')}</h4>
                      <div className="space-y-2 text-sm text-gray-600">
                        <p>{t('security.session.lastLogin')}: {new Date().toLocaleDateString()}</p>
                        <p>{t('security.session.expires')}: {t('security.session.inHours', { hours: 8 })}</p>
                        <p>{t('security.session.loginMethod')}: {t('security.session.sso')}</p>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <ProtectedRoute>
      <SettingsContent />
    </ProtectedRoute>
  );
}