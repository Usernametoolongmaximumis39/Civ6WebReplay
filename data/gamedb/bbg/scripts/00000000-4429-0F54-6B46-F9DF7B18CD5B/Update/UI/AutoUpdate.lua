function UpdateAllMods()
	local enabledMods = GameConfiguration.GetEnabledMods();
	local mods = Modding.GetInstalledMods();
	for _, curMod in ipairs(enabledMods) do
		if not curMod.Official	then		-- 非官方包
			for i,v in ipairs(mods) do
				if curMod.Id == v.Id then
					if v.SubscriptionId and v.SubscriptionId ~= "" then
						Modding.UpdateSubscription(v.SubscriptionId);		-- 更新
					end
				end
			end
		end
	end
end

function Initialize()
	UpdateAllMods()
end
Initialize()