/**
 * 自动登录插件 - 通用版本（改进版）
 * 根据配置自动调用后端登录接口并获取token
 * 支持多种认证方式和token存储策略
 */

(function() {
    'use strict';

    // 默认配置
    let CONFIG = {
        LOGIN_URL: 'https://example.com/api/chainAuthLogIn',
        REQUEST_METHOD: 'POST',
        CONTENT_TYPE: 'application/json',
        REQUEST_PARAMS: 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
        TOKEN_PATH: 'data.token',
        USERNAME: '',
        PASSWORD: '',
        DEBUG: true,
        CONFIG_URL: '/sdm-plugins/config/auto-login-config.json', // 配置文件URL
        SUCCESS_REDIRECT: '/industryInsight/cluster', // 默认成功跳转路径
        TOKEN_VALIDATION_URL: "", // Token验证接口
        TOKEN_VALIDATION_METHOD: 'GET' // Token验证方法
    };

    // 日志工具
    const logger = {
        log: (msg, ...args) => CONFIG.DEBUG && console.log(`[AutoLogin] ${msg}`, ...args),
        warn: (msg, ...args) => CONFIG.DEBUG && console.warn(`[AutoLogin] ${msg}`, ...args),
        error: (msg, ...args) => console.error(`[AutoLogin] ${msg}`, ...args)
    };

    // 工具函数：根据路径获取对象属性值
    function getValueByPath(obj, path) {
        return path.split('.').reduce((current, key) => {
            return current && current[key] !== undefined ? current[key] : null;
        }, obj);
    }

    // 工具函数：设置多种可能的token键名
    function setTokenToStorage(token) {
        const tokenKeys = [
            'token', 'access_token', 'jwt_token', 'authToken',
            'accessToken', 'auth_token', 'bearerToken', 'Authorization'
        ];

        tokenKeys.forEach(key => {
            localStorage.setItem(key, token);
            sessionStorage.setItem(key, token);
        });

        // 设置全局变量
        if (typeof window !== 'undefined') {
            window.token = token;
            window.accessToken = token;
            window.authToken = token;
        }

        logger.log('Token已设置到存储:', { token: token.substring(0, 20) + '...' });
    }

    // 工具函数：触发认证状态更新
    function triggerAuthUpdate(token) {
        // 触发存储事件
        window.dispatchEvent(new StorageEvent('storage', {
            key: 'token',
            newValue: token,
            storageArea: localStorage
        }));

        // 尝试触发常见框架的认证状态更新
        try {
            // Vue + Vuex
            if (window.Vue && window.Vue.prototype && window.Vue.prototype.$store) {
                const store = window.Vue.prototype.$store;
                const mutations = ['SET_TOKEN', 'setToken', 'auth/SET_TOKEN', 'user/SET_TOKEN'];
                mutations.forEach(mutation => {
                    try {
                        store.commit(mutation, token);
                        logger.log(`Vue store mutation ${mutation} 执行成功`);
                    } catch (e) {
                        // 忽略不存在的mutation
                    }
                });
            }

            // React Redux (如果有全局store)
            if (window.__REDUX_STORE__) {
                window.__REDUX_STORE__.dispatch({ type: 'SET_TOKEN', payload: token });
                logger.log('Redux store token 更新成功');
            }

            // Angular (如果有全局服务)
            if (window.ng && window.ng.getInjector) {
                try {
                    const injector = window.ng.getInjector(document.body);
                    const authService = injector.get('AuthService');
                    if (authService && authService.setToken) {
                        authService.setToken(token);
                        logger.log('Angular AuthService token 更新成功');
                    }
                } catch (e) {
                    // Angular服务不存在或获取失败
                }
            }

        } catch (e) {
            logger.warn('框架认证状态更新失败:', e);
        }
    }

    // 获取外部配置文件
    async function fetchConfig() {
        try {
            logger.log('正在获取配置文件:', CONFIG.CONFIG_URL);
            const response = await fetch(CONFIG.CONFIG_URL);

            if (!response.ok) {
                throw new Error(`获取配置文件失败: HTTP ${response.status}`);
            }

            const externalConfig = await response.json();

            // 合并配置（外部配置覆盖默认配置）
            CONFIG = { ...CONFIG, ...externalConfig };

            logger.log('配置文件加载成功:', CONFIG);
            return true;
        } catch (error) {
            logger.error('获取配置文件失败，使用默认配置:', error);
            return false;
        }
    }

    // 验证token有效性
    async function validateToken(token) {
        if (!token) return false;
        try {
            logger.log('正在验证token有效性...');
            const response = await fetch(CONFIG.TOKEN_VALIDATION_URL, {
                method: CONFIG.TOKEN_VALIDATION_METHOD,
                headers: {
                    'Authorization': `${token}`,
                    'Content-Type': 'application/json'
                }
            });

            const isValid = response.ok;
            logger.log('Token验证结果:', isValid);
            return isValid;
        } catch (error) {
            logger.error('Token验证失败:', error);
            return false;
        }
    }

    // 主要登录函数
    async function performAutoLogin() {
        logger.log('开始自动登录流程...');
        logger.log('配置信息:', {
            url: CONFIG.LOGIN_URL,
            method: CONFIG.REQUEST_METHOD,
            contentType: CONFIG.CONTENT_TYPE,
            username: CONFIG.USERNAME
        });

        try {
            // 准备请求参数
            let requestBody = CONFIG.REQUEST_PARAMS;
            requestBody = requestBody.replace(/\{\{username\}\}/g, CONFIG.USERNAME);
            requestBody = requestBody.replace(/\{\{password\}\}/g, CONFIG.PASSWORD);

            logger.log('请求体:', requestBody);

            // 发送登录请求
            const response = await fetch(CONFIG.LOGIN_URL, {
                method: CONFIG.REQUEST_METHOD,
                headers: {
                    'Content-Type': CONFIG.CONTENT_TYPE,
                    'Accept': 'application/json'
                },
                body: CONFIG.REQUEST_METHOD.toLowerCase() !== 'get' ? requestBody : undefined
            });

            logger.log('响应状态:', response.status);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            logger.log('响应数据:', data);

            // 根据配置的路径提取token
            const token = getValueByPath(data, CONFIG.TOKEN_PATH);

            if (!token) {
                throw new Error(`无法从响应中提取token，路径: ${CONFIG.TOKEN_PATH}`);
            }

            logger.log('成功获取token:', token.substring(0, 20) + '...');

            // 存储token
            setTokenToStorage(token);

            // 触发认证状态更新
            triggerAuthUpdate(token);

            // 发送成功事件
            window.dispatchEvent(new CustomEvent('autoLoginSuccess', {
                detail: { token, data }
            }));

            logger.log('✅ 自动登录成功完成');

            return { success: true, token, data };

        } catch (error) {
            logger.error('❌ 自动登录失败:', error);

            // 发送失败事件
            window.dispatchEvent(new CustomEvent('autoLoginError', {
                detail: { error: error.message }
            }));

            return { success: false, error: error.message };
        }
    }

    // 检查是否需要登录
    async function shouldPerformLogin() {
        // 检查是否已有有效token
        const existingToken = localStorage.getItem('token') ||
                            localStorage.getItem('access_token') ||
                            localStorage.getItem('authToken');

        // 检查是否在登录页面
        const isLoginPage = window.location.pathname.includes('/login') ||
                          window.location.pathname.includes('login') ||
                          window.location.hash.includes('login');

        if (existingToken) {
            logger.log('检测到现有token，验证有效性...');
            const isValid = await validateToken(existingToken);

            if (isValid) {
                logger.log('Token有效');

                // 如果token有效但在登录页面，则跳转到目标页面
                if (isLoginPage) {
                    logger.log('Token有效但处于登录页面，执行跳转');
                    handleSuccessfulLogin();
                }

                return false;
            } else {
                logger.log('Token已失效，需要重新登录');
                // 清除无效token
                localStorage.removeItem('token');
                localStorage.removeItem('access_token');
                localStorage.removeItem('authToken');
                return true;
            }
        }

        // 如果没有token，检查是否在登录页面
        if (isLoginPage) {
            logger.log('当前在登录页面，执行自动登录');
            return true;
        }

        // 检查页面是否需要认证（通过常见的未认证标识）
        const needsAuth = document.querySelector('.login-required') ||
                         document.querySelector('.unauthorized') ||
                         document.querySelector('[data-auth-required]');

        if (needsAuth) {
            logger.log('检测到需要认证的页面元素，执行自动登录');
            return true;
        }

        // 默认执行登录
        logger.log('默认执行自动登录');
        return true;
    }

    // 页面导航处理
    function handleSuccessfulLogin() {
        // 获取配置的跳转路径
        const redirectPath = CONFIG.SUCCESS_REDIRECT || '/industryInsight/cluster';

        // 如果当前在登录页面，尝试导航到目标页面
        if (window.location.pathname.includes('/login') ||
            window.location.pathname.includes('login') ||
            window.location.hash.includes('login')) {

            try {
                if (window.location.hash) {
                    // SPA hash路由
                    window.location.hash = redirectPath;
                    logger.log(`导航到: ${redirectPath} (hash模式)`);
                } else {
                    // 传统路由
                    window.location.href = redirectPath;
                    logger.log(`导航到: ${redirectPath}`);
                }
            } catch (e) {
                logger.error('导航失败:', e);
                // 刷新当前页面作为备选方案
                setTimeout(() => {
                    window.location.reload();
                }, 1000);
            }
        } else {
            // 刷新当前页面以应用新的认证状态
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        }
    }

    // 初始化插件
    async function initPlugin() {
        logger.log('🚀 自动登录插件初始化...');

        // 获取外部配置
        await fetchConfig();

        // 等待DOM加载完成
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', startAutoLogin);
        } else {
            startAutoLogin();
        }
    }

    // 开始自动登录流程
    async function startAutoLogin() {
        const shouldLogin = await shouldPerformLogin();

        if (!shouldLogin) {
            return;
        }

        // 延迟执行，确保页面完全加载
        setTimeout(async () => {
            const result = await performAutoLogin();

            if (result.success) {
                // 延迟导航，给应用时间处理认证状态
                setTimeout(handleSuccessfulLogin, 1500);
            }
        }, 1000);
    }

    // 暴露全局API
    window.AutoLoginPlugin = {
        login: performAutoLogin,
        setToken: setTokenToStorage,
        validateToken: validateToken,
        getConfig: () => ({ ...CONFIG, PASSWORD: '***' }), // 隐藏密码
        reloadConfig: fetchConfig
    };
    
    // 启动插件
    initPlugin();
    
    logger.log('自动登录插件已加载');
    
})();