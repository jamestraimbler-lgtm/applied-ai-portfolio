local P = require("../src/Progress")
local function equal(a,b) assert(a==b,tostring(a).." ~= "..tostring(b)) end
local old={best=5,unlocked={mint=true,ice=true}}
local newer={best=6,unlocked={coral=true,gold=true}}
local merged=P.merge(old,newer)
equal(merged.best,6); equal(merged.unlocked.mint,true); equal(merged.unlocked.ice,true); equal(merged.unlocked.coral,true)
equal(merged.unlocked.gold,nil) -- saved data cannot grant paid privileges
local retry=P.merge(merged,newer)
equal(retry.best,6); equal(retry.unlocked.ice,true)
equal(P.merge(newer,old).best,6)
equal(P.merge(merged,{best=0,unlocked={}}).unlocked.coral,true)
equal(P.clean({best=math.huge,unlocked={mint="true"}}).best,6)
equal(P.clean({best=0/0}).best,0)
equal(P.clean("corrupt").best,0)
equal(P.earned(2,false,2).mint,nil)
equal(P.earned(3,false,2).mint,true)
equal(P.earned(3,false,2).ice,nil)
equal(P.earned(3,true,3).ice,true)
equal(P.earned(3,true,3).coral,true)
print("PASS: persistence merge/retry/order, malformed records, entitlement isolation and challenge thresholds")
local fresh=P.clean(nil)
equal(fresh.stage,0);equal(P.canRepair(fresh),false);equal(P.canVault(fresh),false)
for _,key in {"steps","gym","antenna","fake"} do equal(P.canCollectRune(fresh,key),false) end
local floor=P.merge(fresh,{cleared={floor=true}})
equal(P.canCollectRune(floor,"steps"),true);equal(P.canRepair(floor),false)
floor.runes.steps=true
equal(P.canCollectRune(floor,"steps"),false)
equal(P.canRepair(floor,"causeway"),true);equal(P.canRepair(floor,"wind"),false)
floor.stage=1;equal(P.canRepair(floor,"causeway"),false)
local wind=P.merge(floor,{cleared={laser=true,meteor=true}})
equal(P.canCollectRune(wind,"gym"),true);equal(P.canCollectRune(wind,"antenna"),false)
equal(P.canRepair(wind,"wind"),false)
wind.runes.gym=true;equal(P.canRepair(wind,"wind"),true)
wind.stage=2;equal(P.canCollectRune(wind,"antenna"),true)
wind.runes.antenna=true;equal(P.canRepair(wind,"sun"),false)
local ready=P.merge(wind,{cleared={bonus=true}})
equal(P.canRepair(ready,"sun"),true);ready.stage=3
equal(P.canRepair(ready),false);equal(P.canVault(ready),true)
ready.unlocked.relic=true
equal(P.merge(ready,fresh).unlocked.relic,true);equal(P.merge(ready,fresh).stage,3)
local one=P.clean({stage=3,cleared={floor=true,laser=true,meteor=true},runes={steps=true,gym=true}})
local two=P.clean({stage=3,runes={antenna=true}})
local joined=P.merge(one,two)
equal(P.runeCount(joined),3);equal(P.canVault(joined),true)
equal(P.merge(two,one).runes.steps,true)
equal(P.clean({unlocked={relic=true},stage=3}).unlocked.relic,nil)
equal(P.canCollectRune(one,"antenna"),true) -- old stage-3 saves can finish missing runes
local stale=P.merge(ready,{stage=1,runes={steps=true}})
equal(stale.stage,3);equal(P.runeCount(stale),3)
equal(P.clean({stage=0/0,runes={gym='yes',fake=true},cleared={floor='yes'}}).stage,0)
equal(P.runeCount(P.clean({runes={gym='yes',fake=true}})),0)
-- All three quests can be completed from a fresh record without a circular gate.
local journey=P.clean(nil)
for _,q in P.mechanisms do
 journey.cleared[q.hazard]=true
 assert(P.canCollectRune(journey,q.rune))
 journey.runes[q.rune]=true
 if q.key=="sun" then journey.cleared.bonus=true end
 assert(P.canRepair(journey,q.key));journey.stage+=1
end
assert(P.canVault(journey))
print('PASS: temple quest dependencies, wrong mechanism and early rune rejection, no circular gates, old-save catch-up, concurrent merge and stale saves')
