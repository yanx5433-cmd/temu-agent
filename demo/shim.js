/* 在线演示回放层：拦截页面对 /api/** 的请求，用 demo/snapshot.json 里录制的真实响应喂回页面。
   页面本身（admin.html）不改一行逻辑——演示和跑起来的本机版本是同一份 UI 代码。 */
(function () {
  var nativeFetch = window.fetch.bind(window);
  var S = null;
  var ready = nativeFetch(new URL('snapshot.json', location.href).href)
    .then(function (r) { return r.json(); })
    .then(function (j) { S = j; state.gets = clone(j.gets); return j; });

  var state = { gets: null, drafts: {}, sent: {}, knowledgeSeq: 900, replySeq: 9000 };

  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function resp(body, status) {
    var code = status || 200;
    return {
      ok: code < 400, status: code, statusText: code < 400 ? 'OK' : 'Error',
      headers: { get: function () { return 'application/json'; } },
      json: function () { return Promise.resolve(body); },
      text: function () { return Promise.resolve(JSON.stringify(body)); },
    };
  }
  function fail(status, detail) { return resp({ detail: detail }, status); }
  function err400(detail) { return fail(400, detail); }

  var OFFLINE = '在线演示不发起外部请求，也不写数据库。';
  var DIMS = ['margin', 'competition', 'demand', 'growth', 'logistics', 'stability'];

  function norm(s) { return String(s || '').toLowerCase().replace(/[\s，。？！?!,.;：:、]/g, ''); }

  /* ---------- GET ---------- */
  function getPath(key) {
    if (state.gets[key]) return state.gets[key];
    var bare = key.split('?')[0];
    if (state.gets[bare]) return state.gets[bare];
    return null;
  }

  /* ---------- 评分实验台：与 services/sensitivity.py 同式，前端真算 ---------- */
  function totalOf(sub, w) {
    return DIMS.reduce(function (a, d) { return a + (parseFloat(sub[d]) || 0) * (parseFloat(w[d]) || 0); }, 0);
  }
  function rankOrder(rows, w) {
    return rows.map(function (_, i) { return i; }).sort(function (a, b) {
      return totalOf(rows[b], w) - totalOf(rows[a], w) || a - b;
    });
  }
  function whatIf(body) {
    var w = (body && body.weights) || {};
    var k = Math.min((body && body.k) || 5, 21);
    var missing = DIMS.filter(function (d) { return !(d in w); });
    if (missing.length) return err400('缺少分项权重：' + missing.join(', ') + '（六个维度必须都给）');
    var sum = DIMS.reduce(function (a, d) { return a + parseFloat(w[d]); }, 0);
    if (Math.abs(sum - 1) > 0.001) return err400('评分权重之和必须为1，当前 ' + sum.toFixed(4));

    var rows = (state.gets['/candidates'].items || []).map(function (item) {
      var c = state.gets['/candidates/' + item.id] || item;
      var sub = {};
      DIMS.forEach(function (d) { sub[d] = parseFloat(c[d + '_score']) || 0; });
      return { id: c.id, label: (c.normalized_title || '').slice(0, 40), rec: c.recommendation,
               oldTotal: c.total_score, sub: sub };
    });
    if (!rows.length) return resp({ ok: true, items: [], changed_top: [] });

    var base = state.gets['/settings'].score_weights || {};
    var baseRank = rankOrder(rows, base);
    var newRank = rankOrder(rows, w);
    var baseTop = baseRank.slice(0, k), newTop = newRank.slice(0, k);
    var xor = newTop.filter(function (i) { return baseTop.indexOf(i) < 0; })
      .concat(baseTop.filter(function (i) { return newTop.indexOf(i) < 0; }));
    var items = newRank.slice(0, k * 2).map(function (idx, pos) {
      var r = rows[idx];
      return {
        rank: pos + 1, candidate_id: r.id, title: r.label,
        new_score: Math.round(totalOf(r.sub, w) * 100) / 100,
        old_score: r.oldTotal, old_rank: baseRank.indexOf(idx) + 1,
        sub: r.sub,
      };
    });
    return resp({
      ok: true, k: k, items: items,
      top_set_changed: Array.from(new Set(xor.map(function (i) { return rows[i].label; }))).sort(),
      ranks_moved: newRank.filter(function (idx, pos) { return baseRank.indexOf(idx) !== pos; }).length,
      total_candidates: rows.length,
    });
  }

  /* ---------- POST ---------- */
  function postConversation(body) {
    var want = norm(body && body.question);
    if (!want) return err400('请输入问题');
    var hit = (S.posts['/conversations'] || []).filter(function (c) { return norm(c.question) === want; })[0];
    if (!hit) {
      return err400('这条问题没有录制过，回放不了（' + OFFLINE + '）可点客服工作台里的任意一条已有会话，'
        + '或试试：这个发夹有哪些颜色可以选 / 我要退款 / 我的订单 20240901123 现在到哪里了 / How long does shipping take to the US?');
    }
    return resp(clone(hit.conversation));
  }

  function generateReply(convId) {
    var map = S.posts['/conversations/{id}/generate-reply'] || {};
    var d = map[String(convId)];
    if (!d) return fail(404, '会话不存在');
    var copy = clone(d);
    var over = state.drafts[copy.id];
    if (over) Object.assign(copy, over);
    return resp(copy);
  }

  function approveReply(rid, body) {
    var map = S.posts['/conversations/{id}/generate-reply'] || {};
    var base = null;
    Object.keys(map).forEach(function (k) { if (map[k] && map[k].id === rid) base = map[k]; });
    if (!base) return fail(404, '草稿不存在');
    var cur = state.drafts[rid] || {};
    if ((cur.approval_status || base.approval_status) === 'sent') return err400('草稿已发送');
    state.drafts[rid] = Object.assign(cur, {
      approval_status: 'approved',
      final_reply: (body && body.final_reply) || base.generated_reply,
      approved_by: (body && body.approver) || 'admin',
      edited: !!(body && body.final_reply && body.final_reply !== base.generated_reply),
    });
    return resp(Object.assign(clone(base), state.drafts[rid]));
  }

  function sendReply(rid) {
    var map = S.posts['/conversations/{id}/generate-reply'] || {};
    var base = null;
    Object.keys(map).forEach(function (k) { if (map[k] && map[k].id === rid) base = map[k]; });
    if (!base) return fail(404, '草稿不存在');
    var cur = state.drafts[rid] || {};
    if ((cur.approval_status || base.approval_status) !== 'approved' && (cur.approval_status || base.approval_status) !== 'sent') {
      return err400('回复必须先经人工审批（当前默认 L1）');
    }
    state.drafts[rid] = Object.assign(cur, { approval_status: 'sent' });
    return resp(Object.assign(clone(base), state.drafts[rid]));
  }

  function approveCandidate(id) {
    var item = (state.gets['/candidates'].items || []).filter(function (c) { return c.id === id; })[0];
    if (!item) return fail(404, '候选不存在');
    var chk = (S.posts['/candidates/{id}/compliance-check'] || {})[String(id)];
    var status = chk && chk.status;
    if (!status || status === 'REJECT') return err400('合规结果为 REJECT 或尚未检查，禁止审批');
    if (status === 'REVIEW') return err400('合规结果为 REVIEW，需先人工确认资料后再审批');
    item.approved = true;
    var detail = state.gets['/candidates/' + id];
    if (detail) { detail.approved = true; detail.approved_by = 'admin'; }
    return resp({ ok: true, candidate_id: id, approved: true });
  }

  function saveSettings(body) {
    body = body || {};
    var updated = {};
    var s = state.gets['/settings'];
    if (body.score_weights) {
      var w = body.score_weights;
      var total = Object.keys(w).reduce(function (a, k) { return a + parseFloat(w[k]); }, 0);
      if (Math.abs(total - 1) > 0.001) return err400('评分权重之和必须为1，当前 ' + total);
      s.score_weights = w; updated.score_weights = w;
    }
    ['target_markets', 'automation_level', 'auto_reply_enabled', 'category_defaults'].forEach(function (k) {
      if (body[k] !== undefined && body[k] !== null) { s[k] = body[k]; updated[k] = body[k]; }
    });
    return resp({ ok: true, updated: updated });
  }

  function saveIntegration(body) {
    body = body || {};
    if (body.adapter === 'official') {
      if (!(body.app_key && body.app_secret)) {
        var rec = S.posts['/settings/integrations/temu/official_without_keys'];
        return resp(rec.body, rec.status);
      }
      return err400(OFFLINE + ' official 模式要真的向 TEMU Partner Platform 换 token，本地运行才会发起。');
    }
    var caps = (S.posts['/settings/integrations/temu'] || {})[body.adapter];
    if (!caps) return err400('未知接入方式：' + body.adapter);
    state.gets['/settings/integrations'].temu.adapter = body.adapter;
    return resp({ ok: true, adapter: body.adapter, capabilities: caps.capabilities, config_stored: caps.config_stored });
  }

  function addKnowledge(body) {
    var list = state.gets['/knowledge'];
    var doc = {
      id: ++state.knowledgeSeq, type: body.type || 'faq', title: body.title || '',
      content: body.content || '', keywords: body.keywords || [], source: 'manual',
      created_at: S.captured_at, updated_at: S.captured_at,
    };
    if (!doc.title || !doc.content) return err400('title 与 content 不能为空');
    list.items.unshift(doc);
    list.total = list.items.length;
    return resp(doc);
  }

  function routePost(path, body) {
    var m;
    if (path === '/selection/run') return resp(clone(S.posts['/selection/run'].body));
    if (path === '/scoring/whatif') return whatIf(body);
    if (path === '/conversations') return postConversation(body);
    if (path === '/knowledge') return addKnowledge(body);
    if (path === '/settings') return saveSettings(body);
    if (path === '/settings/integrations/temu') return saveIntegration(body);
    if (path === '/imports/csv' || path === '/outcomes/import' || path === '/imports/products') {
      return err400('上传类接口在在线演示里关闭（' + OFFLINE + '）本地跑一份，几秒就能把自己的一批商品灌进去。');
    }
    if ((m = path.match(/^\/candidates\/(\d+)\/compliance-check$/))) {
      return resp(clone((S.posts['/candidates/{id}/compliance-check'] || {})[m[1]]));
    }
    if ((m = path.match(/^\/candidates\/(\d+)\/approve$/))) return approveCandidate(parseInt(m[1], 10));
    if ((m = path.match(/^\/conversations\/(\d+)\/generate-reply$/))) return generateReply(parseInt(m[1], 10));
    if ((m = path.match(/^\/replies\/(\d+)\/approve$/))) return approveReply(parseInt(m[1], 10), body);
    if ((m = path.match(/^\/replies\/(\d+)\/send$/))) return sendReply(parseInt(m[1], 10));
    return fail(404, '演示未录制该接口：' + path);
  }

  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    if (!/^\/api(\/|$)/.test(url)) return nativeFetch(input, init);
    var path = url.replace(/^\/api/, '').split('?')[0];
    var method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    return ready.then(function () {
      if (method === 'GET') {
        var data = getPath(url.replace(/^\/api/, ''));
        if (data === null) return fail(404, '演示未录制该接口：' + path);
        return resp(clone(data));
      }
      var body = null;
      if (init && typeof init.body === 'string') { try { body = JSON.parse(init.body); } catch (e) { body = {}; } }
      return routePost(path, body);
    });
  };

  window.__DEMO__ = {
    get snapshot() { return S; },
    get state() { return state; },
    ready: ready,
  };
})();
