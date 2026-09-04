(function(){
const SDK=window.__HERMES_PLUGIN_SDK__;
if(!SDK){console.error("Hermes Alive: SDK not available");return}
const React = SDK.React || (typeof window!=='undefined' && window.React) || null;
if(!React){console.error('Hermes Alive: React not available');return}
const{useState,useEffect,useCallback}=React;
const _c=SDK.components || {};
const Card=_c.Card || function(p){return React.createElement('div',Object.assign({className:'alive-card'},p||{}),p&&p.children)};
const CardHeader=_c.CardHeader || function(p){return React.createElement('div',{className:'alive-card-header'},p&&p.children)};
const CardTitle=_c.CardTitle || function(p){return React.createElement('div',{className:'alive-card-title'},p&&p.children)};
const CardContent=_c.CardContent || function(p){return React.createElement('div',{className:'alive-card-content'},p&&p.children)};
const Button=_c.Button || function(p){return React.createElement('button',p,p&&p.children)};
const Badge=_c.Badge || function(p){return React.createElement('span',{className:'alive-badge'},p&&p.children)};
const Tabs=_c.Tabs || function(p){return React.createElement('div',p,p&&p.children)};
const TabsList=_c.TabsList || function(p){return React.createElement('div',{className:'alive-tabs'},p&&p.children)};
const TabsTrigger=_c.TabsTrigger || function(p){return React.createElement('button',{className:'alive-tab'},p&&p.children)};
const fetchJSON = SDK.fetchJSON || function(u){return fetch(u).then(function(r){return r.json()})};

const API="/api/plugins/hermes-alive";

function AlivePanel(){
  const[tab,setTab]=useState("status");
  const[status,setStatus]=useState(null);
  const[history,setHistory]=useState([]);
  const[users,setUsers]=useState([]);
  const[selectedUser,setSelectedUser]=useState("__global__");
  const[loading,setLoading]=useState(true);

  const loadStatus=useCallback(async()=>{
    try{
      const s=await fetchJSON(`${API}/status?user_id=${selectedUser}`);
      setStatus(s);
    }catch(e){console.error(e)}
  },[selectedUser]);

  const loadHistory=useCallback(async()=>{
    try{
      const h=await fetchJSON(`${API}/history?user_id=${selectedUser}&limit=30`);
      setHistory(h);
    }catch(e){console.error(e)}
  },[selectedUser]);

  const loadUsers=useCallback(async()=>{
    try{
      const u=await fetchJSON(`${API}/users`);
      setUsers(u);
    }catch(e){console.error(e)}
  },[]);

  useEffect(()=>{loadUsers()},[loadUsers]);
  useEffect(()=>{loadStatus();loadHistory();setLoading(false)},[loadStatus,loadHistory]);

  if(loading)return React.createElement("div",{className:"alive-empty"},"加载中...");

  return React.createElement("div",{className:"alive-panel"},
    React.createElement("div",{className:"alive-tab-bar"},
      React.createElement("span",{style:{fontWeight:"bold",marginRight:"1rem"}},"💓 Alive"),
      ["status","history","config"].map(t=>
        React.createElement("button",{key:t,className:`alive-tab ${tab===t?"active":""}`,onClick:()=>setTab(t)},
          {status:"状态",history:"历史",config:"配置"}[t])
      )
    ),
    tab==="status"&&React.createElement(StatusView,{status,users,selectedUser,setSelectedUser,loadStatus}),
    tab==="history"&&React.createElement(HistoryView,{history}),
    tab==="config"&&React.createElement(ConfigView)
  );
}

function StatusBar({label,value,max,color}){
  const pct=Math.min(100,Math.max(0,(value/max)*100));
  return React.createElement("div",null,
    React.createElement("div",{style:{display:"flex",justifyContent:"space-between",fontSize:"0.85rem"}},
      React.createElement("span",null,label),
      React.createElement("span",{style:{color}},value+"/"+max)
    ),
    React.createElement("div",{className:"alive-bar"},
      React.createElement("div",{className:"alive-bar-fill",style:{width:pct+"%",background:color}})
    )
  );
}

function StatusView({status,users,selectedUser,setSelectedUser,loadStatus}){
  if(!status)return React.createElement("div",{className:"alive-empty"},"无数据");
  return React.createElement(React.Fragment,null,
    users.length>0&&React.createElement("div",{style:{marginBottom:"1rem",display:"flex",alignItems:"center",gap:"0.5rem"}},
      React.createElement("span",{style:{fontSize:"0.8rem",color:"#888"}},"用户:"),
      React.createElement("select",{value:selectedUser,onChange:e=>{setSelectedUser(e.target.value)},
        style:{background:"#1a1a2e",color:"#fff",border:"1px solid #333",borderRadius:"4px",padding:"0.3rem"}
      },
        React.createElement("option",{value:"__global__"},"全局"),
        users.map(u=>React.createElement("option",{key:u,value:u},u))
      ),
      React.createElement(Button,{onClick:loadStatus,style:{fontSize:"0.75rem"}},"刷新")
    ),
    React.createElement("div",{className:"alive-grid"},
      React.createElement(Card,{className:"alive-card"},
        React.createElement(CardHeader,null,React.createElement(CardTitle,null,"⏰ 时钟")),
        React.createElement(CardContent,null,
          React.createElement("div",{className:"value"},{waking:"清醒",winding_down:"犯困",sleeping:"睡眠",warming_up:"刚醒"}[status.clock_phase]||status.clock_phase),
          React.createElement("div",{className:"label"},"当前阶段")
        )
      ),
      React.createElement(Card,{className:"alive-card"},
        React.createElement(CardHeader,null,React.createElement(CardTitle,null,"⚡ 精力")),
        React.createElement(CardContent,null,
          React.createElement("div",{className:"value",color:status.energy>60?"#4ade80":status.energy>30?"#facc15":"#f87171"},status.energy+"/100"),
          React.createElement("div",{className:"label"},status.energy_label),
          React.createElement(StatusBar,{label:"",value:status.energy,max:100,color:status.energy>60?"#4ade80":status.energy>30?"#facc15":"#f87171"})
        )
      ),
      React.createElement(Card,{className:"alive-card"},
        React.createElement(CardHeader,null,React.createElement(CardTitle,null,"😰 压力")),
        React.createElement(CardContent,null,
          React.createElement("div",{className:"value"},status.stress+"/100"),
          React.createElement("div",{className:"label"},status.stress_mode),
          React.createElement(StatusBar,{label:"",value:status.stress,max:100,color:status.stress>60?"#f87171":status.stress>30?"#facc15":"#4ade80"})
        )
      )
    ),
    React.createElement(Card,{className:"alive-card",style:{marginBottom:"1rem"}},
      React.createElement(CardHeader,null,React.createElement(CardTitle,null,"😊 情绪 (PAD)")),
      React.createElement(CardContent,null,
        ["p","a","d"].map(d=>{
          const val=d==="p"?status.pad_p:d==="a"?status.pad_a:status.pad_d;
          const name={p:"P 愉悦性",a:"A 激活度",d:"D 支配度"}[d];
          const color=val>0.3?"#4ade80":val<-0.3?"#f87171":"#facc15";
          return React.createElement("div",{key:d,className:"alive-emotion-row"},
            React.createElement("span",{className:"alive-emotion-name"},name),
            React.createElement("span",{className:"alive-emotion-val",style:{color}},
              (val>0?"+":"")+val.toFixed(3))
          );
        }),
        React.createElement("div",{style:{marginTop:"0.5rem",fontSize:"0.8rem",color:"#888"}},
          "情绪: ",React.createElement("span",{style:{color:"#fff"}},status.emotion_label))
      )
    ),
    React.createElement(Card,{className:"alive-card"},
      React.createElement(CardHeader,null,React.createElement(CardTitle,null,"❤️ 情感关系")),
      React.createElement(CardContent,null,
        [{k:"bond_c",l:"C 亲密度"},{k:"bond_d",l:"D 依赖度"},{k:"bond_i",l:"I 在意度"},{k:"bond_t",l:"T 信任度"}].map(({k,l})=>{
          const val=status[k]||0;
          const color=val>0.3?"#4ade80":val<-0.3?"#f87171":"#facc15";
          return React.createElement("div",{key:k,className:"alive-emotion-row"},
            React.createElement("span",{className:"alive-emotion-name"},l),
            React.createElement("span",{className:"alive-emotion-val",style:{color}},
              (val>0?"+":"")+val.toFixed(3))
          );
        }),
        status.trauma_active&&React.createElement("div",{style:{marginTop:"0.5rem"}},
          React.createElement("span",{className:"alive-badge alive-badge-red"},"创伤窗口活跃"))
      )
    )
  );
}

function HistoryView({history}){
  if(!history||history.length===0)return React.createElement("div",{className:"alive-empty"},"暂无历史数据");
  return React.createElement(Card,{className:"alive-card"},
    React.createElement(CardHeader,null,React.createElement(CardTitle,null,"📊 情绪历史")),
    React.createElement(CardContent,null,
      React.createElement("div",{className:"alive-history"},
        history.map((h,i)=>
          React.createElement("div",{key:i,className:"alive-history-item"},
            React.createElement("span",{style:{color:"#888",marginRight:"0.5rem"}},
              h.timestamp),
            React.createElement("span",null,
              "P:",h.pad_p?.toFixed(2)," A:",h.pad_a?.toFixed(2)," D:",h.pad_d?.toFixed(2),
              " | C:",h.bond_c?.toFixed(2)," D:",h.bond_d_rel?.toFixed(2),
              " I:",h.bond_i?.toFixed(2)," T:",h.bond_t?.toFixed(2)),
            h.trigger_event&&React.createElement("span",{style:{color:"#666",marginLeft:"0.5rem"}},
              "(",h.trigger_event,")")
          )
        )
      )
    )
  );
}

function ConfigView(){
  const[config,setConfig]=useState(null);
  useEffect(()=>{fetchJSON(`${API}/config`).then(setConfig).catch(console.error)},[]);
  if(!config)return React.createElement("div",{className:"alive-empty"},"加载中...");
  var sections=Object.entries(config).map(function(entry){
    var section=entry[0], values=entry[1]||{};
    var rows=Object.entries(values).map(function(kv){
      return React.createElement("div",{key:kv[0],className:"alive-emotion-row"},
        React.createElement("span",{className:"alive-emotion-name"},kv[0]),
        React.createElement("span",{className:"alive-emotion-val"},String(kv[1])));
    });
    return React.createElement("div",{key:section,style:{marginBottom:"1rem"}},
      React.createElement("div",{style:{fontWeight:"bold",fontSize:"0.85rem",color:"#aaa",textTransform:"uppercase",marginBottom:"0.3rem"}},section),
      rows);
  });
  return React.createElement(Card,{className:"alive-card"},
    React.createElement(CardHeader,null,React.createElement(CardTitle,null,"⚙️ 配置")),
    React.createElement(CardContent,null,sections)
  );
}

window.__HERMES_PLUGINS__.register("hermes-alive",AlivePanel);
})();
